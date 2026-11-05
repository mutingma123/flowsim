"""A FlowSim model drawn in the model builder. Edit it like any FlowSim script."""

from flowsim import Model, exponential, uniform

model = Model(time_unit="minutes")
customers = model.source(
    name="Customers",
    interarrival=exponential(mean=3),
    types={"Walk-in": 0.6, "Appointment": 0.4},
)
desk = model.station(
    name="Desk",
    capacity=1,
    service_time=1,
)
exam = model.station(
    name="Exam",
    capacity=2,
    service_time=uniform(
        low=3,
        high=6,
    ),
    staffing=[(0, 1), (60, 2)],
    shift_end="finish",
)
model.route([customers, desk])
model.route([exam, model.exit])
model.branch(desk, {exam: 0.3, model.exit: 0.7}, types=["Appointment"])
model.route([desk, exam], types=["Walk-in"])

results = model.run(
    duration=240,
    seed=42,
)
print(results)
