import enoki
import unittest


class FakeCommon:
    def __init__(self, entries):
        self.__dict__.update(**entries)


class FakeFSM:
    def __init__(self, init_state):
        self.msg = None
        if isinstance(init_state, dict):
            self.common = FakeCommon(init_state)
        else:
            self.common = init_state


def makeTestingInternalState(dictState):
    """Takes a dictionary mirroring the internal state
       a mortise State expects to see and creates that
       object to be used in testing correct transisitions"""
    return FakeFSM(dictState)


class EnokiTest(unittest.TestCase):

    def _next_state(self, fsm, state):
        while True:
            try:
                result_state = state.tick(fsm)
                if result_state is not None:
                    break
            except (enoki.StateRetryLimitError,
                    enoki.StateTimedOut) as e:
                fsm.msg = e
        return result_state

    def assertNextState(self, enoki_state, next_state,
                        initial_state=None, msg=None,
                        enter_next_state=False):
        current_state = enoki_state()
        fake_fsm = FakeFSM(initial_state or {})
        fake_fsm.msg = msg
        result_state = self._next_state(fake_fsm, current_state)
        self.assertIs(result_state, next_state)
        if enter_next_state:
            _next_state = next_state()
            _next_state.on_enter_handler(fake_fsm)

    def assertTimedOutState(self, enoki_state, next_state,
                            initial_state=None):
        self.assertNextState(enoki_state, next_state, initial_state,
                             enoki.StateTimedOut())

    def assertFailState(self, enoki_state, next_state, initial_state=None):
        self.assertNextState(enoki_state, next_state, initial_state,
                             enoki.StateRetryLimitError())

    def _single_transition(self, enoki_state, initial_state=None, msg=None):
        current_state = enoki_state()
        fake_fsm = FakeFSM(initial_state or {})
        fake_fsm.msg = msg
        return current_state.tick(fake_fsm)

    def assertNoTransition(self, enoki_state, initial_state=None, msg=None):
        self.assertIn(
            self._single_transition(enoki_state, initial_state, msg),
            enoki.BLOCKING_RETURNS)

    def assertSomeTransition(self, enoki_state, initial_state=None,
                             msg=None):
        self.assertIsNotNone(
            self._single_transition(enoki_state, initial_state, msg))
