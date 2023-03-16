# Lightning ⚡ Hivemind

[![lightning](https://img.shields.io/badge/-Lightning_2.0+-792ee5?logo=pytorchlightning&logoColor=white)](https://lightning.ai/)
[![PyPI Status](https://badge.fury.io/py/lightning-hivemind.svg)](https://badge.fury.io/py/lightning-hivemind)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/lightning-hivemind)](https://pypi.org/project/lightning-hivemind/)
[![PyPI Status](https://pepy.tech/badge/lightning-hivemind)](https://pepy.tech/project/lightning-hivemind)
[![Deploy Docs](https://github.com/Lightning-AI/lightning-Hivemind/actions/workflows/docs-deploy.yml/badge.svg)](https://lightning-ai.github.io/lightning-Hivemind/)

[![General checks](https://github.com/Lightning-AI/lightning-hivemind/actions/workflows/ci-checks.yml/badge.svg?event=push)](https://github.com/Lightning-AI/lightning-hivemind/actions/workflows/ci-checks.yml)
[![CI testing](https://github.com/Lightning-AI/lightning-hivemind/actions/workflows/ci-testing.yml/badge.svg?event=push)](https://github.com/Lightning-AI/lightning-hivemind/actions/workflows/ci-testing.yml)
[![Build Status](https://dev.azure.com/Lightning-AI/compatibility/_apis/build/status/Lightning-AI.lightning-Hivemind?branchName=main)](https://dev.azure.com/Lightning-AI/compatibility/_build/latest?definitionId=43&branchName=main)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/Lightning-AI/lightning-Hivemind/main.svg)](https://results.pre-commit.ci/latest/github/Lightning-AI/lightning-Hivemind/main)

Collaborative Training tries to solve the need for top-tier multi-GPU servers by allowing you to train across unreliable machines,
such as local machines or even preemptible cloud compute across the internet.

Under the hood, we use [Hivemind](https://github.com/learning-at-home/hivemind) which provides de-centralized training across the internet.

To use Collaborative Training, you need to first this extension.

```bash
pip install -U lightning-Hivemind
```

The `HivemindStrategy` accumulates gradients from all processes that are collaborating until they reach a `target_batch_size`. By default, we use the batch size
of the first batch to determine what each local machine batch contributes towards the `target_batch_size`. Once the `target_batch_size` is reached, an optimizer step
is made on all processes.

When using `HivemindStrategy` note that you cannot use gradient accumulation (`accumulate_grad_batches`). This is because Hivemind manages accumulation internally.

```py
from lightning import Trainer
from lightning_hivemind.strategy import HivemindStrategy

trainer = Trainer(strategy=HivemindStrategy(target_batch_size=8192), accelerator="gpu", devices=1)
```

Followed by:

```bash
python train.py
# Other machines can connect running the same command:
# INITIAL_PEERS=... python train.py
# or passing the peers to the strategy:"
# HivemindStrategy(initial_peers=...)"
```

A helper message is printed once your training begins, which shows you how to start training on other machines using the same code.
