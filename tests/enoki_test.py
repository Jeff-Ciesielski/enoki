import enoki
import enoki.testing as testing_enoki

# Can be run with any testing framework that uses unittest


class CommonState:
    def __init__(self):
        self.entered = False


class FirstState(enoki.State):
    def on_state(self, st):
        return NextState


class NextState(enoki.State):
    def on_enter(self, st):
        st.common.entered = True


class FirstState2(enoki.State):
    def on_state(self, st):
        if st.common.cool:
            return CoolState
        else:
            return HotState


class CoolState: pass
class HotState: pass


class LoopState(enoki.State):
    def on_state(self, st):
        if st.common.num < 5:
            st.common.num += 1
            return None
        else:
            return LoopDoneState


class LoopDoneState: pass


class TimeoutState(enoki.State):
    def on_state(self, st):
        raise enoki.StateTimedOut

    def on_timeout(self, st):
        return TimedOutState


class TimedOutState: pass


class RetryLimitState(enoki.State):
    def on_state(self, st):
        raise enoki.StateRetryLimitError

    def on_timeout(self, st):
        return TimedOutState

    def on_fail(self, st):
        return FailedState


class FailedState: pass


class ErrorState(enoki.State):
    def on_state(self, st):
        pass

    def on_timeout(self, st):
        return TimedOutState

    def on_fail(self, st):
        return FailedState


class MsgState(enoki.State):
    def on_state(self, st):
        if st.msg is None:
            return
        elif st.msg and st.msg == "good":
            return GoodState
        else:
            return BadState


class GoodState: pass
class BadState: pass


class NoneState(enoki.State):
    def on_state(self, st):
        return None


class RepeatState(enoki.State):
    def on_state(self, st):
        return enoki.Repeat


class OnEnterState(enoki.State):
    def on_enter(self, st):
        self.entered = True

    def on_state(self, st):
        if self.entered:
            return NextState
        else:
            return FirstState


class TestEnoki(testing_enoki.EnokiTest):
    def testFirstToNext(self):
        self.assertNextState(FirstState, NextState)

    def testFirstState2CoolToCool(self):
        self.assertNextState(FirstState2, CoolState, {"cool": True})

    def testFirstState2CoolToHot(self):
        self.assertNextState(FirstState2, HotState, {"cool": False})

    def testLoopStateFinishes(self):
        self.assertNextState(LoopState, LoopDoneState, {"num": 0})

    def testTimeoutStateTimesOut(self):
        self.assertNextState(TimeoutState, TimedOutState)

    def testFailStateFails(self):
        self.assertNextState(RetryLimitState, FailedState)

    def testErrorStateToTimedOut(self):
        self.assertTimedOutState(ErrorState, TimedOutState)

    def testErrorStateToFailed(self):
        self.assertFailState(ErrorState, FailedState)

    def testMsgToGood(self):
        self.assertNextState(MsgState, GoodState, msg="good")

    def testMsgToBad(self):
        self.assertNextState(MsgState, BadState, msg="bad")

    def testNoTransition(self):
        self.assertNoTransition(NoneState)

    def testRetryNoTransition(self):
        self.assertNoTransition(RepeatState)

    def testOnEnter(self):
        self.assertNextState(OnEnterState, NextState)

    def testNextOnEnter(self):
        common_state = CommonState()
        self.assertFalse(common_state.entered)
        self.assertNextState(OnEnterState, NextState, common_state,
                             enter_next_state=True)
        self.assertTrue(common_state.entered)
