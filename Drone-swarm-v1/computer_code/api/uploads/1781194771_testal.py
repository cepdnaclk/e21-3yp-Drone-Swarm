arm()
takeoff(0.25)
for i in range(4):
    move(0.2, 0, 0)
    wait(2)
    log("pos:", get_position(), "battery:", get_battery("alpha"))
land()