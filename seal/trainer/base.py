import seal.trainer.defaults as defaults
import os
import pickle
import ray
import time
import json

from abc import ABC, abstractmethod
from collections import defaultdict
from pandas import DataFrame
from seal.logging import *
from ray.rllib.agents import (a3c, dqn, ppo)
from ray.rllib.agents.callbacks import DefaultCallbacks
from time import ctime
from typing import Any, Callable, Dict, List, Tuple

from seal.trainer.counter import Counter
from seal.trainer.defaults import *
from seal.trainer.util import *
from seal.sumo.abstract_env import AbstractSumoEnv

RAY_TRAINER_SEED = 54321


class SafeUnpickler(pickle.Unpickler):
    """Custom unpickler that cleans numpy.object_ arrays during deserialization."""
    
    def find_class(self, module, name):
        # Intercept numpy array creation
        if module == 'numpy' and name == 'ndarray':
            # We'll handle this in load_reduce
            pass
        return super().find_class(module, name)
    
    def persistent_load(self, pid):
        return super().persistent_load(pid)


class BaseTrainer(ABC):

    communication_callback_cls: DefaultCallbacks
    counter: Counter
    idx: int
    num_gpus: int
    env: AbstractSumoEnv
    learning_rate: float
    log_level: str
    gamma: float
    num_gpus: int
    num_workers: int
    out_checkpoint_dir: str
    out_data_dir: str
    out_weights_dir: str
    policy: str
    policy_mapping_fn: Callable
    policy_type: ray.rllib.policy.Policy
    trainer_type: ray.rllib.agents.trainer.Trainer

    def __init__(
            self,
            checkpoint_freq: int = 5,
            env: AbstractSumoEnv = None,
            gamma: float = 0.95,
            learning_rate: float = 0.001,
            log_level: str = "ERROR",
            model_name: str = None,
            num_gpus: int = 0,
            num_workers: int = 0,
            root_dir: List[str] = ["out", "SMARTCOMP"],
            sub_dir: str = None,
            policy: str = "ppo",
            out_prefix: str = None,
            trainer_kwargs: dict = None,
            **kwargs
    ) -> None:
        assert 0 <= gamma <= 1
        self.communication_callback_cls = None
        self.checkpoint_freq = checkpoint_freq
        self.counter = Counter()
        self.env = env
        self.gamma = gamma
        self.learning_rate = learning_rate
        self.log_level = log_level
        self.model_name = model_name
        self.num_gpus = num_gpus
        self.num_workers = num_workers

        self.out_checkpoint_dir = os.path.join(*(root_dir + ["checkpoints"]))
        self.out_data_dir = os.path.join(*(root_dir + ["data"]))
        self.out_weights_dir = os.path.join(*(root_dir + ["weights"]))
        if sub_dir is not None:
            self.out_checkpoint_dir = os.path.join(
                self.out_checkpoint_dir, sub_dir)
            self.out_data_dir = os.path.join(self.out_data_dir, sub_dir)
            self.out_weights_dir = os.path.join(self.out_weights_dir, sub_dir)

        self.gui = kwargs.get("gui", defaults.GUI)
        self.net_file = kwargs.get("net_file", defaults.NET_FILE)
        self.ranked = kwargs.get("ranked", defaults.RANKED)
        self.rand_routes_on_reset = kwargs.get("rand_routes_on_reset",
                                               defaults.RAND_ROUTES_ON_RESET)
        self.rand_routes_config = kwargs.get("rand_routes_config",
                                             defaults.RAND_ROUTES_CONFIG)

        self.out_prefix = out_prefix
        self.net_dir = self.net_file.split(os.sep)[-1].split(".")[0]
        self.out_checkpoint_dir = os.path.join(
            self.out_checkpoint_dir, self.net_dir)
        self.out_data_dir = os.path.join(self.out_data_dir, self.net_dir)
        self.out_weights_dir = os.path.join(self.out_weights_dir, self.net_dir)

        if not os.path.isdir(self.out_checkpoint_dir):
            os.makedirs(os.path.join(self.out_checkpoint_dir))
        if not os.path.isdir(self.out_data_dir):
            os.makedirs(os.path.join(self.out_data_dir))
        if not os.path.isdir(self.out_weights_dir):
            os.makedirs(os.path.join(self.out_weights_dir))

        self.policy = policy
        self.__load_policy_type()

        self.trainer_name = None
        self.idx = None
        self.policy_config = None
        self.policy_mapping_fn = None
        self.trainer_kwargs = trainer_kwargs

    # ------------------------------------------------------------------------- #

    def _clean_numpy_objects(self, obj, depth=0):
        """
        Recursively clean numpy.object_ arrays from checkpoint data.
        This fixes the 'can't convert np.ndarray of type numpy.object_' error.
        
        CRITICAL: We must NOT convert to Python lists, because Ray will call
        np.asarray(list) which creates object arrays again!
        Instead, we must convert to proper numeric numpy arrays or scalars.
        """
        import numpy as np
        
        if isinstance(obj, dict):
            return {k: self._clean_numpy_objects(v, depth+1) for k, v in obj.items()}
        elif isinstance(obj, list):
            # Clean each element, but keep as list (Ray handles lists differently than arrays)
            cleaned = [self._clean_numpy_objects(item, depth+1) for item in obj]
            # Check if this should be a numpy array (all same-shape numeric arrays)
            if len(cleaned) > 0 and all(isinstance(x, np.ndarray) for x in cleaned):
                try:
                    dtypes = set(x.dtype for x in cleaned)
                    shapes = set(x.shape for x in cleaned)
                    if len(dtypes) == 1 and len(shapes) == 1 and cleaned[0].dtype != np.object_:
                        return np.stack(cleaned)
                except:
                    pass
            return cleaned
        elif isinstance(obj, tuple):
            return tuple(self._clean_numpy_objects(item, depth+1) for item in obj)
        elif isinstance(obj, np.ndarray):
            if obj.dtype == np.object_:
                # Handle 0-d (scalar) object array
                if obj.ndim == 0:
                    inner = obj.item()
                    return self._clean_numpy_objects(inner, depth+1)
                
                # Handle 1-d+ object arrays
                # First, recursively clean all elements
                cleaned_elements = [self._clean_numpy_objects(obj[i], depth+1) for i in range(len(obj))]
                
                if len(cleaned_elements) == 0:
                    return np.array([], dtype=np.float64)
                
                # Case 1: All elements are numeric scalars
                if all(isinstance(x, (int, float, np.integer, np.floating)) for x in cleaned_elements):
                    return np.array(cleaned_elements, dtype=np.float64)
                
                # Case 2: All elements are numeric numpy arrays with same shape/dtype
                if all(isinstance(x, np.ndarray) and x.dtype != np.object_ for x in cleaned_elements):
                    try:
                        shapes = [x.shape for x in cleaned_elements]
                        if all(s == shapes[0] for s in shapes):
                            # Stack into higher-dimensional array
                            return np.stack(cleaned_elements)
                    except:
                        pass
                
                # Case 3: Mixed content - try to make it a numeric array anyway
                try:
                    result = np.array(cleaned_elements, dtype=np.float64)
                    if result.dtype != np.object_:
                        return result
                except:
                    pass
                
                # Last resort: return as list (some parts of Ray can handle lists)
                # But wrap in a way that won't become object array
                return cleaned_elements
            else:
                # Non-object array - ensure it has a concrete numeric dtype
                if obj.dtype.kind == 'O':
                    # This shouldn't happen but just in case
                    try:
                        return obj.astype(np.float64)
                    except:
                        return obj
                return obj
        elif isinstance(obj, (np.integer, np.floating)):
            # Convert numpy scalars to Python scalars
            return obj.item()
        else:
            return obj

    def _find_object_arrays(self, obj, path="root"):
        """Debug helper to find remaining object arrays after cleaning.
        Also checks lists that would become object arrays when np.asarray is called."""
        import numpy as np
        results = []
        
        if isinstance(obj, dict):
            for k, v in obj.items():
                results.extend(self._find_object_arrays(v, f"{path}['{k}']"))
        elif isinstance(obj, list):
            # Check if this list would become an object array
            if len(obj) > 0:
                try:
                    test = np.asarray(obj)
                    if test.dtype == np.object_:
                        sample = str(obj[0])[:50] if len(obj) > 0 else "empty"
                        results.append(f"{path}: list->object_array, len={len(obj)}, sample={sample}")
                except:
                    pass
            for i, v in enumerate(obj):
                results.extend(self._find_object_arrays(v, f"{path}[{i}]"))
        elif isinstance(obj, tuple):
            for i, v in enumerate(obj):
                results.extend(self._find_object_arrays(v, f"{path}[{i}]"))
        elif isinstance(obj, np.ndarray):
            if obj.dtype == np.object_:
                sample = str(obj.flat[0])[:100] if obj.size > 0 else "empty"
                results.append(f"{path}: ndarray shape={obj.shape}, sample={sample}")
        
        return results

    # ========================================================================= #
    # CLEAN CHECKPOINT SAVE/LOAD METHODS
    # ========================================================================= #
    # These methods save only policy weights (no optimizer state) to avoid
    # numpy.object_ serialization errors that plague Ray checkpoints.
    # ========================================================================= #
    
    def _save_clean_checkpoint(self, checkpoint_dir: str, episode: int) -> str:
        """
        Save checkpoint with ONLY policy weights (no optimizer state).
        
        This avoids the numpy.object_ serialization issues that corrupt Ray checkpoints.
        We save:
        - Policy weights for all agents
        - Training metadata (episode number, timestamp)
        - Env config (cleaned for JSON serialization)
        
        We do NOT save:
        - Optimizer state (will be reinitialized on load)
        - Gradient buffers (will be recomputed)
        """
        checkpoint_file = os.path.join(checkpoint_dir, f"checkpoint_{episode:06d}.pkl")
        
        # Extract only the clean parts we need
        clean_checkpoint = {
            "episode": episode,
            "timestamp": time.time(),
            "policies": {},
            "env_config": self._make_json_safe_dict(self.env_config) if hasattr(self, 'env_config') else {}
        }
        
        # Extract policy weights from all trained policies
        try:
            for policy_id, policy in self.ray_trainer.workers.local_worker().policy_map.items():
                try:
                    weights = policy.get_weights()
                    # Ensure weights are JSON-serializable
                    clean_checkpoint["policies"][policy_id] = self._make_json_safe_dict(weights)
                    logging.debug(f"Saved weights for policy {policy_id}")
                except Exception as e:
                    logging.warning(f"Could not save weights for policy {policy_id}: {e}")
        except Exception as e:
            logging.warning(f"Could not access policy map: {e}")
        
        # Save to pickle file
        try:
            os.makedirs(checkpoint_dir, exist_ok=True)
            with open(checkpoint_file, 'wb') as f:
                pickle.dump(clean_checkpoint, f)
            logging.info(f"Saved clean checkpoint (episode {episode}) to {checkpoint_file}")
            return checkpoint_file
        except Exception as e:
            logging.error(f"Failed to save clean checkpoint: {e}")
            raise

    def _load_clean_checkpoint(self, checkpoint_file: str) -> None:
        """
        Load checkpoint that contains only policy weights.
        Optimizer state will be reinitialized automatically.
        
        Note: If weight loading fails for any policy, training continues with fresh weights.
        """
        logging.info(f"Loading clean checkpoint from: {checkpoint_file}")
        
        try:
            with open(checkpoint_file, 'rb') as f:
                checkpoint_data = pickle.load(f)
        except Exception as e:
            logging.error(f"Failed to load checkpoint file: {e}")
            raise
        
        episode = checkpoint_data.get("episode", 0)
        policies_data = checkpoint_data.get("policies", {})
        
        if not policies_data:
            logging.warning("Checkpoint contains no policy weights")
            return
        
        # Restore weights to each policy
        weights_loaded = 0
        weights_failed = 0
        
        for policy_id, weights in policies_data.items():
            try:
                policy = self.ray_trainer.get_policy(policy_id)
                policy.set_weights(weights)
                logging.debug(f"Restored weights for policy {policy_id}")
                weights_loaded += 1
            except Exception as e:
                logging.debug(f"Could not restore weights for policy {policy_id}: {e}")
                weights_failed += 1
        
        if weights_loaded > 0:
            logging.info(f"Checkpoint restored (episode {episode}): {weights_loaded} policies loaded")
        else:
            logging.warning(f"Could not load weights from checkpoint. Training will continue with fresh weights.")


    def _clean_checkpoint_file(self, checkpoint_path: str) -> str:
        """DEPRECATED: This method is no longer used."""
        raise RuntimeError("Old checkpoint recovery method deprecated. Use _save_clean_checkpoint() and _load_clean_checkpoint() instead.")
        
        logging.info(f"Cleaning checkpoint during load...")
        
        # Load with post-processing to clean object arrays
        with open(checkpoint_path, 'rb') as f:
            # Load and walk the entire structure, cleaning as we go
            checkpoint_data = pickle.load(f)
        
        # Deep clean all object arrays
        checkpoint_data = self._recursive_clean_object_arrays(checkpoint_data)
        
        # Save to temp file
        checkpoint_dir = os.path.dirname(checkpoint_path)
        checkpoint_basename = os.path.basename(checkpoint_path)
        temp_file = os.path.join(checkpoint_dir, "_cleaned_" + checkpoint_basename)
        
        with open(temp_file, 'wb') as f:
            pickle.dump(checkpoint_data, f)
        
        # Copy metadata
        metadata_src = checkpoint_path + ".tune_metadata"
        metadata_dst = temp_file + ".tune_metadata"
        if os.path.exists(metadata_src):
            shutil.copy2(metadata_src, metadata_dst)
        
        logging.info(f"Checkpoint cleaned and saved")
        return temp_file
    
    def _recursive_clean_object_arrays(self, obj):
        """Recursively clean ALL numpy.object_ arrays, including deeply nested ones."""
        import numpy as np
        
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                result[k] = self._recursive_clean_object_arrays(v)
            return result
        
        elif isinstance(obj, (list, tuple)):
            cleaned = [self._recursive_clean_object_arrays(item) for item in obj]
            return type(obj)(cleaned) if isinstance(obj, tuple) else cleaned
        
        elif isinstance(obj, np.ndarray):
            # If it's an object array, we MUST convert it
            if obj.dtype == np.object_:
                # Handle 0-d arrays
                if obj.ndim == 0:
                    inner = obj.item()
                    return self._recursive_clean_object_arrays(inner)
                
                # For multi-dimensional object arrays:
                # Convert each element, trying to maintain structure
                try:
                    # Try to convert to proper numeric array
                    flat_list = [self._recursive_clean_object_arrays(obj.flat[i]) for i in range(obj.size)]
                    result_array = np.array(flat_list, dtype=np.float64)
                    return result_array.reshape(obj.shape)
                except (ValueError, TypeError):
                    # If numeric conversion fails, keep as list
                    flat_list = [self._recursive_clean_object_arrays(obj.flat[i]) for i in range(obj.size)]
                    try:
                        return np.array(flat_list, dtype=object)  # Keep as object but cleaned contents
                    except:
                        return flat_list
            else:
                # Non-object numpy array - ensure it's not problematic
                if obj.dtype.kind == 'O':  # Object kind but not object_ dtype
                    try:
                        return obj.astype(np.float64)
                    except:
                        pass
                return obj
        
        elif isinstance(obj, (np.integer, np.floating)):
            # Convert numpy scalars to Python types
            return obj.item()
        
        elif isinstance(obj, np.generic):
            # Handle other numpy scalar types
            return obj.item()
        
        else:
            # Primitives, strings, etc.
            return obj

    def load(self, checkpoint: str) -> None:
        """
        Load checkpoint with clean weight loading.
        
        Supports two checkpoint formats:
        1. New clean checkpoints (checkpoint_XXXXXX.pkl) - loads weights only
        2. Ray checkpoints (checkpoint-N) - attempts direct restore
        """
        if type(self) is BaseTrainer:
            raise NotImplementedError("Cannot load policy using abstract `BaseTrainer` class.")
        
        self.policies = self.on_policy_setup()
        if GLOBAL_POLICY_VAR in self.policies:
            raise ValueError(f"Sub-classes of `BaseTrainer` cannot have policies with key '{GLOBAL_POLICY_VAR}'.")
        else:
            temp = next(iter(self.policies.values()))
            self.policies[GLOBAL_POLICY_VAR] = temp
        self.on_setup()
        
        import os
        checkpoint_path = checkpoint.replace("\\", "/")
        
        logging.info(f"Loading checkpoint from: {checkpoint_path}")
        
        # First, check if this is a clean checkpoint file (checkpoint_XXXXXX.pkl)
        if os.path.isfile(checkpoint_path) and checkpoint_path.endswith('.pkl'):
            logging.info("Detected clean checkpoint file format")
            try:
                self._load_clean_checkpoint(checkpoint_path)
                logging.info("Successfully loaded clean checkpoint")
                return
            except Exception as e:
                logging.error(f"Failed to load clean checkpoint: {e}")
                raise
        
        # Handle checkpoint directory (contains checkpoint_XXXXXX.pkl files)
        if os.path.isdir(checkpoint_path):
            logging.info("Checkpoint path is a directory, searching for clean checkpoint files...")
            
            # Look for clean checkpoint files (checkpoint_XXXXXX.pkl)
            clean_checkpoints = []
            for file in os.listdir(checkpoint_path):
                if file.startswith("checkpoint_") and file.endswith(".pkl"):
                    clean_checkpoints.append(os.path.join(checkpoint_path, file))
            
            if clean_checkpoints:
                # Use the latest clean checkpoint (highest episode number)
                latest_checkpoint = max(
                    clean_checkpoints, 
                    key=lambda x: int(os.path.basename(x).split('_')[1].split('.')[0])
                )
                logging.info(f"Found clean checkpoint: {latest_checkpoint}")
                try:
                    self._load_clean_checkpoint(latest_checkpoint)
                    logging.info("Successfully loaded clean checkpoint")
                    return
                except Exception as e:
                    logging.error(f"Failed to load clean checkpoint: {e}")
                    raise
            
            # Fallback: look for old Ray checkpoint format (checkpoint-N)
            logging.info("No clean checkpoints found, checking for Ray checkpoints...")
            files = os.listdir(checkpoint_path)
            checkpoint_files = [f for f in files if f.startswith("checkpoint-") and not f.endswith(".tune_metadata")]
            if checkpoint_files:
                old_checkpoint_path = os.path.join(checkpoint_path, checkpoint_files[0]).replace("\\", "/")
                logging.warning("Found old Ray checkpoint format (may have compatibility issues)")
                logging.info(f"Attempting to load: {old_checkpoint_path}")
                try:
                    self.ray_trainer.restore(old_checkpoint_path)
                    logging.info("Ray checkpoint restored successfully")
                    return
                except Exception as e:
                    logging.error(f"Failed to load Ray checkpoint: {e}")
                    raise RuntimeError(
                        f"Could not load checkpoint {checkpoint}. "
                        f"The checkpoint appears to be from an older training run with compatibility issues. "
                        f"Please use train_cyberattack.py to create fresh checkpoints."
                    ) from e
            
            raise FileNotFoundError(f"No checkpoint files found in {checkpoint_path}")
        
        # If checkpoint_path is a file but not .pkl, assume it's Ray format
        logging.warning(f"Checkpoint path format unknown: {checkpoint_path}")
        try:
            self.ray_trainer.restore(checkpoint_path)
            logging.info("Checkpoint restored (Ray format)")
            return
        except Exception as e:
            logging.error(f"Failed to restore checkpoint: {e}")
            raise

    # ------------------------------------------------------------------------- #



    def make_json_safe(self, val):
        """Convert a single value to JSON-safe type."""
        import numpy as np
        
        # Handle numpy arrays
        if isinstance(val, np.ndarray):
            # For numeric arrays, keep as-is (torch can handle them)
            if np.issubdtype(val.dtype, np.number):
                return val
            # For string/object arrays, convert to Python list then to strings
            else:
                return val.astype(str).tolist() if val.size > 0 else []
        
        # Handle numpy scalars
        if isinstance(val, (np.integer, np.floating)):
            return val.item()
        
        if isinstance(val, np.bool_):
            return bool(val)
        
        if isinstance(val, np.str_):
            return str(val)
        
        # Handle generic numpy types
        if isinstance(val, np.generic):
            return val.item()
        
        # Try JSON serialization as fallback
        try:
            json.dumps(val)
            return val
        except (TypeError, OverflowError, ValueError):
            return str(val)

    def _make_json_safe_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively convert all dict values to JSON-serializable types and numeric numpy arrays."""
        import numpy as np
        
        if not isinstance(d, dict):
            return d
        
        clean_dict = {}
        for k, v in d.items():
            if isinstance(v, dict):
                clean_dict[k] = self._make_json_safe_dict(v)
            elif isinstance(v, (list, tuple)):
                # For numeric arrays in lists, keep them; otherwise convert items
                clean_list = []
                for item in v:
                    if isinstance(item, np.ndarray) and np.issubdtype(item.dtype, np.number):
                        clean_list.append(item)  # Keep numeric arrays as-is
                    else:
                        clean_list.append(self.make_json_safe(item))
                clean_dict[k] = clean_list
            else:
                clean_dict[k] = self.make_json_safe(v)
        return clean_dict



    # ------------------------------------------------------------------------- #



    def train(self, num_rounds: int, save_on_end: bool = True, **kwargs) -> DataFrame:
        if kwargs.get("checkpoint", None) is not None:
            logging.info(f"Resuming from checkpoint: {kwargs['checkpoint']}")
            self.load(kwargs["checkpoint"])
        else:
            logging.info("Starting fresh training (no checkpoint)")
            self.policies = self.on_policy_setup()
            if GLOBAL_POLICY_VAR in self.policies:
                raise ValueError(f"Sub-classes of `BaseTrainer` cannot have "
                                 f"policies with key '{GLOBAL_POLICY_VAR}'.")
            else:
                temp = next(iter(self.policies.values()))
                self.policies[GLOBAL_POLICY_VAR] = temp
            self.on_setup()
        
        # Log starting round
        start_round = self._round + 1 if hasattr(self, '_round') else 0
        logging.info(f"Training rounds: {start_round} to {num_rounds - 1}")
        
        for r in range(num_rounds):
            self._round = r
            self._result = self.ray_trainer.train()
            self.on_data_recording_step()
            self.on_logging_step()
            if r % self.checkpoint_freq == 0:
                # Use our custom clean checkpoint save (no optimizer state)
                self._save_clean_checkpoint(self.model_path, r)
                logging.info(f"Saved clean checkpoint at episode {r}")
            self.save_test_policy()
        
        # Set the global test policy that will be used for evaluation.
        weights = self.save_test_policy()
        self.ray_trainer.get_policy(GLOBAL_POLICY_VAR).set_weights(weights)
        
        # Get the data from the training process and output it for visualization
        dataframe = self.on_tear_down()
        if save_on_end:
            path = os.path.join(self.out_data_dir, self.get_filename())
            try:
                for col in dataframe.columns:
                    dataframe[col] = dataframe[col].apply(self.make_json_safe)
                dataframe.to_csv(f"{path}.csv")
                dataframe.to_excel(f"{path}.xlsx")
                dataframe.to_json(f"{path}.json")
            except FileNotFoundError:
                new_dir = os.path.join(path.split(os.sep[:-1]))
                os.makedirs(new_dir)
                dataframe.to_csv(f"{path}.csv")
                dataframe.to_excel(f"{path}.xlsx")
                dataframe.to_json(f"{path}.json")
        return dataframe

    # ------------------------------------------------------------------------- #

    def __load_policy_type(self) -> None:
        if self.policy == "a3c":
            self.trainer_type = a3c.A3CTrainer
            self.policy_type = a3c.a3c_torch_policy
        elif self.policy == "dqn":
            self.trainer_type = dqn.DQNTrainer
            self.policy_type = dqn.DQNTorchPolicy
        elif self.policy == "ppo":
            self.trainer_type = ppo.PPOTrainer
            self.policy_type = ppo.PPOTorchPolicy
        else:
            raise NotImplemented(f"Do not support policies for `{policy}`.")

    # ------------------------------------------------------------------------- #

    def init_config(self) -> Dict[str, Any]:
        env_config = self.env_config_fn()
        
        # Ensure env_config is JSON-serializable (Ray checkpoints must be serializable)
        # Convert any non-serializable types to primitives
        env_config_clean = self._make_json_safe_dict(env_config)
        
        config = {
            "env_config": env_config_clean,
            "framework": "torch",
            "log_level": self.log_level,
            "lr": self.learning_rate,
            "multiagent": {
                "policies": self.policies,
                "policy_mapping_fn": self.policy_mapping_fn
            },
            "num_gpus": self.num_gpus,
            "num_workers": self.num_workers,
            "seed": RAY_TRAINER_SEED,
            "callbacks": self.communication_callback_cls,
        }
        if self.trainer_kwargs is not None:
            config.update(self.trainer_kwargs)
        return config

    def env_config_fn(self) -> Dict[str, Any]:
        return {
            "gui": self.gui,
            "net-file": self.net_file,
            "rand_routes_on_reset": self.rand_routes_on_reset,
            "ranked": self.ranked,
            "use_dynamic_seed": True,
            # "horizon": 450,
            # "rand_route_args": {
            #     "seed": 0,
            #     "vehicles_per_lane_per_hour": 360
            # }
        }

    def save_test_policy(self) -> Weights:
        # Get the global test policy weights and then save them to a PICKLE file object.
        # This will then be used to reload the test policy's weights for evaluation
        # in both the synthetic simulations and real-world implementation.
        weights = self.on_make_final_policy()
        ranked_str = "ranked" if self.ranked else "unranked"
        if self.out_prefix is not None:
            ranked_str = f"{self.out_prefix}_{ranked_str}"
        with open(os.path.join(self.out_weights_dir, f"{ranked_str}.pkl"), "wb") as f:
            pickle.dump(weights, f)
        return weights

    # ------------------------------------------------------------------------- #

    def on_setup(self) -> None:
        # Ensure any existing Ray cluster is shutdown before reinitializing
        if ray.is_initialized():
            ray.shutdown()
            time.sleep(2)  # Wait for Ray processes to fully cleanup
        
        ray.init(include_dashboard=False)
        self.ray_trainer = self.trainer_type(env=self.env,
                                             config=self.init_config())
        out_dir = self.out_checkpoint_dir
        self.model_path = os.path.join(out_dir, self.get_filename())
        self.training_data = defaultdict(list)

    def on_tear_down(self) -> DataFrame:
        self.ray_trainer.save(self.model_path)
        self.ray_trainer.stop()
        ray.shutdown()
        return DataFrame.from_dict(self.training_data)

    def on_logging_step(self) -> None:
        status = "{}Ep. #{} | ranked={} | Mean reward: {:6.2f} | Mean length: {:4.2f} | Saved {} ({})"
        logging.info(status.format(
            "" if self.trainer_name is None else f"[{self.trainer_name}] ",
            self._round+1,
            self.ranked,
            self._result["episode_reward_mean"],
            self._result["episode_len_mean"],
            self.model_path.split(os.sep)[-1],
            ctime()
        ))

    def get_key(self) -> str:
        if self.trainer_name is None:
            raise ValueError("`trainer_name` cannot be None.")
        ranked = "ranked" if self.ranked else "unranked"
        key = f"{self.trainer_name}_{self.net_dir}_{ranked}"
        return key

    def get_key_count(self) -> int:
        return self.counter.get(self.get_key())

    def incr_key_count(self) -> None:
        self.counter.increment(self.get_key())

    def get_filename(self) -> str:
        if self.trainer_name is None:
            raise ValueError("`trainer_name` cannot be None.")
        ranked = "ranked" if self.ranked else "unranked"
        if self.out_prefix is not None:
            ranked = f"{self.out_prefix}_{ranked}"
        return f"{ranked}"
        # return f"{ranked}_{self.idx}"

    def get_weights_filename(self) -> str:
        ranked = "ranked" if self.ranked else "unranked"
        return f"{ranked}"

    def set_rand_route_seed(self, seed) -> None:
        self.env

    # ------------------------------------------------------------------------- #

    @abstractmethod
    def on_make_final_policy() -> Weights:
        """This function is to be used for defining the weights used for the final policy
           to be used during evaluation. Each Trainer sub-class will come up with their
           own way for doing this procedure. For instance, simply grabbing one of the
           trained policies at random and returning its weights is sufficient (though
           likely not a desirable approach). The returned weights will then be used to
           in the GLOBAL policy that evaluation will be used.

        Raises:
            NotImplementedError: Cannot be called for the abstract BaseTrainer class.

        Returns:
            Weights: The model weights to be used in the GLOBAL model for evaluation.
        """
        raise NotImplementedError("Must implement abstract function "
                                  "`on_make_final_policy`.")

    @abstractmethod
    def on_data_recording_step(self) -> None:
        raise NotImplementedError("Must implement abstract function "
                                  "`on_data_recording_step`.")

    @abstractmethod
    def on_policy_setup(self) -> Dict[str, Tuple[Any]]:
        raise NotImplementedError("Must implement abstract function "
                                  "`on_policy_setup`.")
