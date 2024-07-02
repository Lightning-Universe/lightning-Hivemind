:orphan:

################################################################
Hivemind - training on unreliable mixed GPUs across the internet
################################################################

Collaborative Training tries to solve the need for top-tier multi-GPU servers by allowing you to train across unreliable machines,
such as local machines or even preemptible cloud compute across the internet.

Under the hood, we use `Hivemind <https://github.com/learning-at-home/hivemind>`__ which provides de-centralized training across the internet.

.. warning::  This is an :ref:`experimental <versioning:Experimental API>` feature.


To use Collaborative Training, you need to first this extension.

.. code-block:: bash

    pip install lightning-hivemind

This will install both the `Hivemind <https://pypi.org/project/hivemind/>`__ package as well as the ``HivemindStrategy`` for the Lightning Trainer:

Reducing Communication By Overlapping Communication
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

We can reduce the impact of communication across all machines by overlapping communication with our training iterations. In short, we enable communication to happen in the background of training.

Overlap Gradient and State Averaging
""""""""""""""""""""""""""""""""""""

When the target batch size is reached, all processes that are included in the step send gradients and model states to each other. By enabling some flags through
the strategy, communication can happen in the background. This allows training to continue (with slightly outdated weights) but provides us the means
to overlap communication with computation.

.. warning::
    Enabling overlapping communication means convergence will slightly be affected.

.. note::
    Enabling these flags means that you must pass in a ``scheduler_fn`` to the ``HivemindStrategy`` instead of relying on a scheduler from ``configure_optimizers``.
    The optimizer is re-created by Hivemind, and as a result, the scheduler has to be re-created.

.. code-block:: python

    import torch
    from functools import partial
    from lightning import Trainer
    from lightning_hivemind.strategy import HivemindStrategy

    trainer = Trainer(
        strategy=HivemindStrategy(
            target_batch_size=8192,
            delay_state_averaging=True,
            delay_grad_averaging=True,
            delay_optimizer_step=True,
            offload_optimizer=True,  # required to delay averaging
            scheduler_fn=partial(torch.optim.lr_scheduler.ExponentialLR, gamma=...),
        ),
        accelerator="gpu",
        devices=1,
    )

For more information on the strategy capabilities, see the `lightning-hivemind <https://github.com/Lightning-Universe/lightning-hivemind>`__ repo.
