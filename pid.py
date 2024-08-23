from time import time

class PID:
    def __init__(self, setpoint, range=(None, None), Kp=0.0, Ki=0.0, Kd=0.0):
        # self.min = min
        # self.max = max
        self.setpoint = setpoint
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd

        self.proportional = 0
        self.integral = 0
        self.last_error = None
        self.current_time = time()

    def __call__(self, current):
        print(current)
        new_time = time()
        dt = new_time - self.current_time
        self.current_time = new_time
        error = self.setpoint - current
        derror = error - (self.last_error if self.last_error else error)

        self.proportional = self.Kp * error
        # print(self.proportional)
        self.integral += self.Ki * error * dt  # need to avoid the windup
        derivative = self.Kd * derror / dt

        self.last_error = error

        return self.proportional + self.integral + derivative



