log("arm and takeoff test starting")
log("state before", get_state())

wait(10)
log("state before arm", get_state())

arm()
log("armed")
log("state after arm", get_state())

wait(2)

log("takeoff starting")
takeoff(1.0)
log("takeoff command sent")

wait(10)

log("state after takeoff", get_state())
log("arm and takeoff test done")