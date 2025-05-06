import multiprocessing as mp
import os
import time
from typing import Any
from unittest import mock
from unittest.mock import PropertyMock

import hivemind
import pytest
import torch
from lightning_utilities import module_available
from torch import Tensor
from torch.optim import Optimizer

if module_available("lightning"):
    from lightning.pytorch import Trainer
    from lightning.pytorch.demos.boring_classes import BoringModel
    from lightning.pytorch.utilities.exceptions import MisconfigurationException
    from lightning.pytorch.utilities.types import STEP_OUTPUT

    PL_PACKAGE = "lightning.pytorch"
elif module_available("pytorch_lightning"):
    from pytorch_lightning import Trainer
    from pytorch_lightning.demos.boring_classes import BoringModel
    from pytorch_lightning.utilities.exceptions import MisconfigurationException
    from pytorch_lightning.utilities.types import STEP_OUTPUT

    PL_PACKAGE = "pytorch_lightning"
else:
    raise ModuleNotFoundError("You are missing `lightning` or `pytorch-lightning` package, please install it.")

from lightning_hivemind.strategy import HiveMindScheduler, HivemindStrategy


@mock.patch("hivemind.DHT", autospec=True)
def test_strategy(mock_dht):
    strategy = HivemindStrategy(target_batch_size=1)
    trainer = Trainer(strategy=strategy)
    assert trainer.strategy == strategy


@mock.patch.dict(os.environ, {"HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor"}, clear=True)
def test_optimizer_wrapped():
    class TestModel(BoringModel):
        def on_before_backward(self, loss: Tensor) -> None:
            optimizer = self.trainer.optimizers[0]
            assert isinstance(optimizer, hivemind.Optimizer)

    model = TestModel()
    trainer = Trainer(strategy=HivemindStrategy(target_batch_size=1), fast_dev_run=True)
    trainer.fit(model)


@mock.patch.dict(os.environ, {"HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor"}, clear=True)
def test_scheduler_wrapped():
    class TestModel(BoringModel):
        def on_before_backward(self, loss: Tensor) -> None:
            scheduler = self.trainer.lr_scheduler_configs[0].scheduler
            assert isinstance(scheduler, HiveMindScheduler)

        def configure_optimizers(self):
            optimizer = torch.optim.SGD(self.layer.parameters(), lr=0.1)
            return [optimizer], [torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.9)]

    model = TestModel()
    trainer = Trainer(
        strategy=HivemindStrategy(target_batch_size=1),
        fast_dev_run=True,
    )
    trainer.fit(model)


@mock.patch.dict(os.environ, {"HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor"}, clear=True)
def test_ipfs_integration():
    class TestModel(BoringModel):
        def on_before_backward(self, loss: Tensor) -> None:
            scheduler = self.trainer.lr_scheduler_configs[0].scheduler
            assert isinstance(scheduler, HiveMindScheduler)

        def configure_optimizers(self):
            optimizer = torch.optim.SGD(self.layer.parameters(), lr=0.1)
            return [optimizer], [torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.9)]

    model = TestModel()
    trainer = Trainer(
        strategy=HivemindStrategy(target_batch_size=1, use_ipfs=True, use_relay=True, use_auto_relay=True),
        fast_dev_run=True,
    )
    trainer.fit(model)


@mock.patch.dict(
    os.environ,
    {
        "HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor",
        "PL_INITIAL_PEERS": "TEST_PEERS",
    },
    clear=True,
)
@mock.patch("hivemind.DHT", autospec=True)
def test_env_variables_parsed(mock_dht):
    """Test that env variables are parsed correctly."""
    strategy = HivemindStrategy(target_batch_size=1)
    assert strategy._initial_peers == ["TEST_PEERS"]


@mock.patch.dict(os.environ, {"HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor"}, clear=True)
def test_reuse_grad_buffers_warning():
    """Test to ensure we warn when a user overrides `optimizer_zero_grad` and `reuse_grad_buffers` is True."""

    class TestModel(BoringModel):
        def on_before_backward(self, loss: Tensor) -> None:
            optimizer = self.trainer.optimizers[0]
            assert isinstance(optimizer, hivemind.Optimizer)

        def optimizer_zero_grad(self, epoch: int, batch_idx: int, optimizer: Optimizer, optimizer_idx: int):
            pass

    model = TestModel()
    trainer = Trainer(strategy=HivemindStrategy(target_batch_size=1, reuse_grad_buffers=True), fast_dev_run=True)

    with pytest.warns(UserWarning, match="You have overridden `optimizer_zero_grad` which will be disabled."):
        trainer.fit(model)


@pytest.mark.xfail(
    raises=RuntimeError, reason="Training with multiple optimizers is only supported with manual optimization"
)
def test_raise_exception_multiple_optimizers():
    """Test that we raise an exception when multiple optimizers are provided."""

    class TestModel(BoringModel):
        def configure_optimizers(self):
            optimizer = torch.optim.SGD(self.layer.parameters(), lr=0.1)
            lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1)
            return [optimizer, optimizer], [lr_scheduler]

    model = TestModel()
    trainer = Trainer(strategy=HivemindStrategy(target_batch_size=1), fast_dev_run=True)

    with pytest.raises(MisconfigurationException, match="Hivemind only supports training with one optimizer."):
        trainer.fit(model)


@mock.patch(f"{PL_PACKAGE}.utilities.data._extract_batch_size", autospec=True, return_value=[None])
def test_raise_exception_no_batch_size(mock__extract_batch_size):
    """Test that we raise an exception when no batch size is automatically found."""
    model = BoringModel()
    trainer = Trainer(strategy=HivemindStrategy(target_batch_size=1), fast_dev_run=True)

    with pytest.raises(MisconfigurationException, match="Please provide the batch size to the Strategy."):
        trainer.fit(model)


@mock.patch.dict(os.environ, {"HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor"}, clear=True)
@pytest.mark.parametrize(
    ("delay_grad_averaging", "delay_state_averaging", "delay_optimizer_step"),
    [(True, True, True), (False, True, False)],
)
def test_warn_if_argument_passed(delay_grad_averaging, delay_state_averaging, delay_optimizer_step):
    """Ensure that valid combination of HiveMind delay arguments warn if scheduler isn't passed in as a function."""
    model = BoringModel()
    trainer = Trainer(
        strategy=HivemindStrategy(
            target_batch_size=1,
            delay_grad_averaging=delay_grad_averaging,
            delay_state_averaging=delay_state_averaging,
            delay_optimizer_step=delay_optimizer_step,
        ),
        fast_dev_run=True,
    )

    with pytest.warns(UserWarning, match="requires a `scheduler_fn` to be passed to the strategy"):
        trainer.fit(model)


@mock.patch.dict(os.environ, {"HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor"}, clear=True)
@mock.patch("lightning_hivemind.strategy.HivemindStrategy.num_peers", new_callable=PropertyMock)
def test_args_passed_to_optimizer(mock_peers):
    """Test to ensure arguments are correctly passed to the hivemind optimizer wrapper."""
    mock_peers.return_value = 1
    compression = hivemind.ScaledFloat16Compression()
    with mock.patch("hivemind.Optimizer", wraps=hivemind.Optimizer) as mock_optimizer:

        class TestModel(BoringModel):
            def on_before_backward(self, loss: Tensor) -> None:
                args, kwargs = mock_optimizer.call_args
                mock_optimizer.assert_called()
                arguments = {
                    "delay_optimizer_step": True,
                    "delay_state_averaging": True,
                    "state_averaging_compression": compression,
                    "grad_compression": compression,
                    "offload_optimizer": True,
                    "reuse_grad_buffers": True,
                    "target_batch_size": 1,
                }

                for key, value in arguments.items():
                    assert key in kwargs
                    assert value == kwargs[key]

        model = TestModel()
        trainer = Trainer(
            strategy=HivemindStrategy(
                target_batch_size=1,
                reuse_grad_buffers=True,
                delay_state_averaging=True,
                delay_optimizer_step=True,
                offload_optimizer=True,
                grad_compression=compression,
                state_averaging_compression=compression,
            ),
            fast_dev_run=True,
        )
        trainer.fit(model)
        # ensures that after training with `reuse_grad_buffers` we restore the hook
        assert model.optimizer_zero_grad is not None


@mock.patch.dict(os.environ, {"HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor"}, clear=True)
@pytest.mark.parametrize(
    ("host_maddrs", "expected_maddrs"),
    [(None, ["/ip4/0.0.0.0/tcp/0", "/ip4/0.0.0.0/udp/0/quic"]), (["/ip4/127.0.0.1/tcp/0"], ["/ip4/127.0.0.1/tcp/0"])],
)
def test_maddrs(host_maddrs, expected_maddrs):
    """Test that the multiple addresses are correctly assigned."""
    strategy = HivemindStrategy(target_batch_size=1, host_maddrs=host_maddrs)
    assert strategy.dht.kwargs["host_maddrs"] == expected_maddrs


def _run_collab_training_fn(initial_peers, wait_seconds, barrier, recorded_process_peers, recorded_process_steps):
    recorded_peers = []
    recorded_global_steps = []

    class TestModel(BoringModel):
        def on_train_batch_end(self, outputs: STEP_OUTPUT, batch: Any, batch_idx: int, unused: int = 0) -> None:
            time.sleep(wait_seconds)  # add an additional delay to give processes time to sync
            recorded_peers.append(self.trainer.strategy.num_peers)
            recorded_global_steps.append(self.trainer.optimizers[0].local_epoch)

        def on_train_end(self) -> None:
            # wait for all processes to get to the end of training before teardown
            barrier.wait()

    model = TestModel()
    trainer = Trainer(
        max_epochs=1,
        limit_train_batches=16,
        limit_val_batches=0,
        strategy=HivemindStrategy(
            delay_state_averaging=True,
            offload_optimizer=True,
            delay_optimizer_step=True,
            delay_grad_averaging=True,
            target_batch_size=8,
            initial_peers=initial_peers,
            verbose=False,
        ),
    )
    trainer.fit(model)

    recorded_process_peers.append(recorded_peers)
    recorded_process_steps.append(recorded_global_steps)


# TODO: check why it fails with PT 1.12
@pytest.mark.skip
@mock.patch.dict(os.environ, {"HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor"}, clear=True)
@pytest.mark.parametrize(
    ("num_processes", "wait_seconds"),
    [(2, 0.25)],
)
def test_multiple_peers(num_processes, wait_seconds):
    """Test to ensure that if we have two running processes with the same peers, they connect and train successfully."""
    dht_root = hivemind.DHT(start=True)
    barrier = mp.Barrier(num_processes)
    initial_peers = dht_root.get_visible_maddrs()

    with mp.Manager() as manager:
        # allows processes to return their recorded logged peers/steps
        recorded_process_peers = manager.list()
        recorded_process_steps = manager.list()
        processes = [
            mp.Process(
                target=_run_collab_training_fn,
                kwargs={
                    "initial_peers": initial_peers,
                    "wait_seconds": wait_seconds,
                    "barrier": barrier,
                    "recorded_process_peers": recorded_process_peers,
                    "recorded_process_steps": recorded_process_steps,
                },
            )
            for x in range(num_processes)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join()
        # assert that peers increase as expected and we run at-least 1 global step.
        for process_peers, process_steps in zip(recorded_process_peers, recorded_process_steps):
            assert any(num_peer == num_processes for num_peer in process_peers)
            assert any(global_step > 0 for global_step in process_steps)


@pytest.mark.xfail(AssertionError, reason="Trainer.precision_plugin.scaler is not hivemind.GradScaler")  # todo
@pytest.mark.skipif(torch.cuda.device_count() < 1, reason="This test needs at least single GPU.")
@mock.patch.dict(os.environ, {"HIVEMIND_MEMORY_SHARING_STRATEGY": "file_descriptor"}, clear=True)
def test_scaler_updated_precision_16():
    class TestModel(BoringModel):
        def on_fit_start(self) -> None:
            assert isinstance(self.trainer.precision_plugin.scaler, hivemind.GradScaler)
            raise SystemExit

    model = TestModel()
    trainer = Trainer(
        strategy=HivemindStrategy(target_batch_size=1),
        fast_dev_run=True,
        precision=16,
        accelerator="gpu",
        devices=1,
    )
    with pytest.raises(SystemExit):
        trainer.fit(model)
