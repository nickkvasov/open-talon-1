# presence-directory

Reusable presence directory primitives for Open Talon.

This package owns ephemeral thread presence state backed by Valkey:

- connection records keyed by thread and connection id
- participant presence records keyed by thread and participant id
- replacement of the active presence record when one of several connections closes

The initial integration point is `gateway-edge`, which uses this package to
track websocket presence without duplicating the Valkey key layout or
connection reconciliation logic.
