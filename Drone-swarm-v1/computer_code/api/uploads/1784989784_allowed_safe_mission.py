log("arm test starting")
log("state before", get_state())

arm()
log("armed")
log("state after arm", get_state())

wait(10)

disarm()
log("disarmed")
log("state after disarm", get_state())

log("arm test done")