# Enoki - A python state machine framework

Enoki is a synchronous state machine library for event based
systems.

## Features

* Synchronous state-machine event handling
* No external dependencies
* Composable / Reusable state support via pushdown automata
* State timeout and retry limit support
* Directed exception handling + state transitions on exception
* State machine visualization (requires graphviz)

## Requirements

* Python >= 3.10
* GraphViz (Optional for state machine visualization)

## Examples

See the `examples` folder.

## Authors

Enoki was originally developed at [Keyme](www.key.me) under the name Mortise by [Jeff Ciesielski](https://github.com/Jeff-Ciesielski) and [Lianne Lairmore](https://github.com/knithacker) for robotics control.
