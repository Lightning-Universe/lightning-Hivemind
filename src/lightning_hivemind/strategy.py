# Copyright The PyTorch Lightning team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import ipaddress
import logging
import os
import platform
from typing import Any, Callable, Dict, List, Optional, Union

import hivemind
import torch
from lightning_utilities import module_available
from torch import Tensor
from torch.optim import Optimizer

if module_available("lightning"):
    from lightning.fabric.strategies.strategy import TBroadcast
    from lightning.fabric.utilities.types import LRScheduler, ReduceLROnPlateau
    from lightning.pytorch import Trainer
    from lightning.pytorch.accelerators import CPUAccelerator, CUDAAccelerator
    from lightning.pytorch.strategies import Strategy
    from lightning.pytorch.utilities.data import extract_batch_size
    from lightning.pytorch.utilities.exceptions import MisconfigurationException
    from lightning.pytorch.utilities.model_helpers import is_overridden
    from lightning.pytorch.utilities.rank_zero import rank_zero_warn
elif module_available("pytorch_lightning") and module_available("lightning_fabric"):
    from lightning_fabric.strategies.strategy import TBroadcast  # type: ignore[no-redef]
    from lightning_fabric.utilities.types import LRScheduler, ReduceLROnPlateau
    from pytorch_lightning import Trainer  # type: ignore[assignment]
    from pytorch_lightning.accelerators import CPUAccelerator, CUDAAccelerator  # type: ignore[assignment]
    from pytorch_lightning.strategies import Strategy  # type: ignore[assignment]
    from pytorch_lightning.utilities.data import extract_batch_size
    from pytorch_lightning.utilities.exceptions import MisconfigurationException  # type: ignore[assignment]
    from pytorch_lightning.utilities.model_helpers import is_overridden
    from pytorch_lightning.utilities.rank_zero import rank_zero_warn
else:
    raise ModuleNotFoundError("You are missing `lightning` or `pytorch-lightning` package, please install it.")

log = logging.getLogger(__name__)


class HivemindStrategy(Strategy):
    """Provides capabilities to train with Hivemind, collaboratively across the internet with unreliable machines.

    .. warning:: ``HivemindStrategy`` is experimental and subject to change.

    Arguments:
        target_batch_size: When training, the batch size to accumulate to before running a step. The larger this
            batch size, the more work can be done asynchronously without communication.

        run_id: A unique identifier of this training run, used as a common prefix for all DHT keys.
            See ``https://learning-at-home.readthedocs.io/en/latest/user/dht.html``.

        batch_size: The local batch size per process. If not provided, we infer this from the first batch of data
            passed in at training (lazy). Note that this should not change throughout training.

        delay_state_averaging: If enabled (default), average parameters and extra tensors in a background thread;
            if set to False, average parameters synchronously within the
            corresponding :meth:`hivemind.Optimizer.step` call.

        delay_optimizer_step: Run optimizer in background, apply results in future .step. requires
            :paramref:`~lightning_hivemind.strategy.HivemindStrategy.offload_optimizer`.

        delay_grad_averaging: Average gradients in background; requires
            :paramref:`~lightning_hivemind.strategy.HivemindStrategy.offload_optimizer` and
            :paramref:`~lightning_hivemind.strategy.HivemindStrategy.delay_optimizer_step`.

        offload_optimizer: Offload the optimizer to host memory, saving GPU memory for parameters and gradients.

        reuse_grad_buffers: Use the model's gradient buffers (params.grad) for gradient accumulation
            which is more memory efficient. Lightning will automatically disable ``zero_grad``
            in the ``LightningModule``.

        scheduler_fn: callable(optimizer) -> PyTorch LRScheduler or a pre-initialized PyTorch scheduler.
            When using `offload_optimizer`/`delay_optimizer_step`/`delay_state_averaging` ``scheduler_fn``
            is required to be passed to the ``HivemindStrategy``. This is because the optimizer
            is re-created and the scheduler needs to be re-created as well.

        matchmaking_time: When looking for group, wait for peers to join for up to this many seconds.
            Increase if you see "averaged gradients with N peers" where N is below 0.9x on >=25% of epochs.
            Training with low-latency network, decreasing matchmaking_time allows training with smaller batch sizes.

        averaging_timeout: If an averaging step hangs for this long, it will be cancelled automatically.
            Increase averaging_timeout if you see "Proceeding with local gradients" at least 25% of the time.
            Do not set this timeout too high, as it may cause your optimizer to hang
            after some types of network errors.

        verbose: Report internal Hivemind events such as accumulating gradients and running background tasks.

        averager_opts: Additional keyword arguments forwarded to both
            ``GradientAverager`` and ``TrainingStateAverager``.

        host_maddrs: List of multi-addrs to create visible peers for other processes.
            `https://learning-at-home.readthedocs.io/en/latest/user/dht.html#running-across-the-internet`

        initial_peers: If connecting to a running process, a list of initial peers needs to be passed in.
            This can also be set via the env variable ``INITIAL_PEERS``.

        use_ipfs: Use IPFS to find initial_peers. If enabled, you only need to provide /p2p/XXXX part of the
            multiaddrs for the initial_peers (no need to specify a particular IPv4/IPv6 host and port)"

        wait_timeout: a kademlia rpc request is deemed lost if we did not receive a reply in this many seconds,
            useful if `use_ipfs=True`

        bootstrap_timeout: after one of peers responds, await other peers for at most this many seconds

        use_relay: disable circuit relay functionality in libp2p (see https://docs.libp2p.io/concepts/nat/circuit-relay/)

        use_auto_relay: look for libp2p relays to become reachable if we are behind NAT/firewall

        identity_path: Path to a private key file. If defined, makes the peer ID deterministic.
            If the file does not exist, writes a new private key to this file.
    )

        **optimizer_kwargs: kwargs are passed to the :class:`hivemind.Optimizer` class.
    """

    INITIAL_PEERS_ENV: str = "PL_INITIAL_PEERS"
    optimizers: List[Optimizer]

    def __init__(
        self,
        target_batch_size: int,
        run_id: str = "lightning_run",
        batch_size: Optional[int] = None,
        delay_state_averaging: bool = False,
        delay_optimizer_step: Optional[bool] = None,
        delay_grad_averaging: bool = False,
        offload_optimizer: Optional[bool] = None,
        reuse_grad_buffers: bool = False,
        scheduler_fn: Optional[Callable] = None,
        matchmaking_time: float = 5.0,
        averaging_timeout: float = 30.0,
        verbose: bool = False,
        averager_opts: Optional[Dict] = None,
        host_maddrs: Optional[List] = None,
        initial_peers: Optional[Union[str, List]] = None,
        use_ipfs: bool = False,
        wait_timeout: int = 3,
        bootstrap_timeout: Optional[float] = None,
        use_relay: bool = True,
        use_auto_relay: bool = False,
        identity_path: Optional[str] = None,
        **optimizer_kwargs: Any,
    ):
        if platform.system() != "Linux":
            raise MisconfigurationException(
                "To use the `HivemindStrategy`, you must have Hivemind installed and be running on Linux."
                " Install it by running `pip install -U hivemind`."
            )

        super().__init__()
        self._initial_peers = initial_peers
        self._target_batch_size = target_batch_size
        self._batch_size = batch_size
        self._scheduler_fn = scheduler_fn
        self._require_scheduler_fn = delay_optimizer_step or delay_state_averaging or offload_optimizer
        self._opt = None
        self._optimizer_zero_grad_original: Optional[Callable] = None
        self._run_id = run_id
        self._reuse_grad_buffers = reuse_grad_buffers
        self._optimizer_kwargs = dict(
            matchmaking_time=matchmaking_time,
            averaging_timeout=averaging_timeout,
            delay_optimizer_step=delay_optimizer_step,
            delay_state_averaging=delay_state_averaging,
            delay_grad_averaging=delay_grad_averaging,
            offload_optimizer=offload_optimizer,
            averager_opts=averager_opts if averaging_timeout is not None else {"request_timeout": 1.0},
            verbose=verbose,
            reuse_grad_buffers=reuse_grad_buffers,
            **optimizer_kwargs,
        )

        self._parse_env_initial_peers()

        self.dht = hivemind.DHT(
            start=True,
            initial_peers=initial_peers,
            host_maddrs=host_maddrs if host_maddrs is not None else ["/ip4/0.0.0.0/tcp/0", "/ip4/0.0.0.0/udp/0/quic"],
            use_ipfs=use_ipfs,
            ensure_bootstrap_success=True,
            wait_timeout=wait_timeout,
            bootstrap_timeout=bootstrap_timeout,
            use_relay=use_relay,
            use_auto_relay=use_auto_relay,
            identity_path=identity_path,
        )

        visible_addresses = [
            str(a) for a in self.dht.get_visible_maddrs() if not ipaddress.ip_address(a.values()[0]).is_loopback
        ]

        if initial_peers is None:
            log.info(
                "\nOther machines can connect running the same command:\n"
                f"INITIAL_PEERS={','.join(visible_addresses)} python ...\n"
                "or passing the peers to the strategy:\n"
                f"HivemindStrategy(initial_peers='{','.join(visible_addresses)}')"
            )

        self._hivemind_initialized = False

    def _parse_env_initial_peers(self) -> None:
        initial_peers = os.environ.get(self.INITIAL_PEERS_ENV, self._initial_peers)
        self._initial_peers = initial_peers.split(",") if isinstance(initial_peers, str) else self._initial_peers

    @property
    def num_peers(self) -> int:
        if self._opt:
            return self._opt.tracker.global_progress.num_peers
        return 1

    @property
    def root_device(self) -> torch.device:
        if isinstance(self.accelerator, CUDAAccelerator):
            return torch.device(f"cuda:{torch.cuda.current_device()}")
        if isinstance(self.accelerator, CPUAccelerator):
            return torch.device("cpu")
        raise MisconfigurationException(
            f"Was unable to infer device type from the accelerator: {self.accelerator.__class__}."
        )

    @property
    def global_rank(self) -> int:
        return 0

    @property
    def is_global_zero(self) -> bool:
        return True

    def setup(self, trainer: Trainer) -> None:
        self.model_to_device()
        super().setup(trainer)
        if self.precision_plugin.precision == "16":
            self.precision_plugin.scaler = hivemind.GradScaler()

    def _initialize_hivemind(self) -> None:
        if len(self.optimizers) > 1:
            raise MisconfigurationException("Hivemind only supports training with one optimizer.")
        optimizer = self.optimizers[0]

        if self._require_scheduler_fn and self._scheduler_fn is None:
            rank_zero_warn(
                "Enabling `delay_optimizer_step`, `delay_state_averaging` or `offload_optimizer` "
                "requires a `scheduler_fn` to be passed to the strategy if a scheduler is being used "
                "(this is because the optimizer is re-created within Hivemind)."
            )

        scheduler = self._scheduler_fn if self._require_scheduler_fn else None
        params = optimizer.param_groups if self._require_scheduler_fn else None
        optimizer = type(optimizer) if self._require_scheduler_fn else optimizer
        opt = hivemind.Optimizer(
            dht=self.dht,
            run_id=self._run_id,
            params=params,
            optimizer=optimizer,
            scheduler=scheduler,
            target_batch_size=self._target_batch_size,
            batch_size_per_step=self._batch_size,
            **self._optimizer_kwargs,
        )

        if not self._scheduler_fn:
            self._wrap_schedulers(opt)
        opt.load_state_from_peers()
        self.optimizers = [opt]
        self._opt = opt

        if self._reuse_grad_buffers:
            assert self.lightning_module is not None
            self._optimizer_zero_grad_original = self.lightning_module.optimizer_zero_grad
            self._disable_zero_grad()

    def _disable_zero_grad(self) -> None:
        lightning_module = self.lightning_module
        if is_overridden("optimizer_zero_grad", lightning_module):
            assert lightning_module is not None  # `is_overridden` returns False otherwise
            rank_zero_warn(
                "You have overridden `optimizer_zero_grad` which will be disabled."
                " When `HivemindStrategy(reuse_grad_buffers=True)`, the optimizer cannot call zero grad,"
                " as this would delete the gradients before they are averaged."
            )
        assert lightning_module is not None
        lightning_module.optimizer_zero_grad = None  # type: ignore[method-assign,assignment]

    def _wrap_schedulers(self, opt: "hivemind.Optimizer") -> None:
        # wrap schedulers so that they only update when the hivemind optimizer updates
        for scheduler_config in self.lr_scheduler_configs:
            scheduler = scheduler_config.scheduler
            if isinstance(scheduler, ReduceLROnPlateau):
                raise ValueError(
                    f"The `ReduceLROnPlateau` scheduler is not currently supported with `{self.__class__.__name__}`."
                )
            scheduler_config.scheduler = HiveMindScheduler(optimizer=opt, scheduler=scheduler)  # type: ignore[assignment]

    def on_train_batch_start(self, batch: Any, batch_idx: int, dataloader_idx: int = 0) -> None:
        if not self._hivemind_initialized:
            self._hivemind_initialized = True
            # todo (sean): we could technically support a dynamic batch size by inferring each step
            # and passing it to the ``hivemind.Optimizer``.
            if self._batch_size is None:
                try:
                    self._batch_size = extract_batch_size(batch)
                    log.info(f"Found per machine batch size automatically from the batch: {self._batch_size}")
                except (MisconfigurationException, RecursionError) as err:
                    raise MisconfigurationException(
                        "We tried to infer the batch size from the first batch of data. "
                        "Please provide the batch size to the Strategy by "
                        "``Trainer(strategy=HivemindStrategy(batch_size=x))``. "
                    ) from err
            self._initialize_hivemind()

    def reduce(self, tensor: Union[Any, Tensor], *args: Any, **kwargs: Any) -> Union[Any, Tensor]:
        return tensor

    def all_gather(self, tensor: Tensor, group: Optional[Any] = None, sync_grads: bool = False) -> Tensor:
        return tensor

    def model_to_device(self) -> None:
        assert self.model is not None
        self.model.to(self.root_device)

    def barrier(self, *args: Any, **kwargs: Any) -> None:
        pass

    def broadcast(self, obj: TBroadcast, src: int = 0) -> TBroadcast:
        return obj

    def teardown(self) -> None:
        if self._optimizer_zero_grad_original is not None and self.lightning_module is not None:
            # re-enable `optimizer_zero_grad`
            self.lightning_module.optimizer_zero_grad = (  # type: ignore[method-assign]
                self._optimizer_zero_grad_original
            )

        if self._opt:
            self._opt.shutdown()
        log.info("Shutting down hivemind DHT.")
        self.dht.shutdown()
        super().teardown()


class HiveMindScheduler:
    """Wrapper for schedulers to prevent Lightning from stepping the scheduler too soon.

    This code ensures that we only step when the HiveMind optimizer reaches the global step.
    """

    base_lrs: List[float]

    def __init__(self, optimizer: "hivemind.Optimizer", scheduler: LRScheduler) -> None:
        # copy most of the `Scheduler` methods into this instance. `__del__` is skipped in case the scheduler has
        # implemented custom logic which we would not want to call on destruction of the `HiveMindScheduler`
        self.__dict__ = {k: v for k, v in scheduler.__dict__.items() if k not in ("step", "__del__")}

        self.optimizer = optimizer
        self.scheduler = scheduler
        self.current_step = -1

    def step(self, epoch: Optional[int] = None) -> None:
        while self.current_step < self.optimizer.local_epoch:
            self.scheduler.step(epoch=epoch)
            self.current_step += 1

    def load_state_dict(self, state_dict: Dict) -> None:
        self.scheduler.load_state_dict(state_dict)

    def state_dict(self) -> Dict:
        return self.scheduler.state_dict()
