# vidigi (Visual Interactive Dynamics and Integrated Graphical Insights)

---

## Introduction

Visual display of the outputs of discrete event simulations in simpy have been identified as one of the limitations of simpy, potentially hindering adoption of FOSS simulation in comparison to commercial modelling offerings or GUI FOSS alternatives such as JaamSim.

> When compared to commercial DES software packages that are commonly used in health research, such as Simul8, or AnyLogic, a limitation of our approach is that we do not display a dynamic patient pathway or queuing network that updates as the model runs a single replication. This is termed Visual Interactive Simulation (VIS) and can help users understand where process problems and delays occur in a patient pathway; albeit with the caveat that single replications can be outliers. A potential FOSS solution compatible with a browser-based app could use a Python package that can represent a queuing network, such as NetworkX, and displaying results via matplotlib. If sophisticated VIS is essential for a FOSS model then researchers may need to look outside of web apps; for example, salabim provides a powerful FOSS solution for custom animation of DES models.
> -  Monks T and Harper A. Improving the usability of open health service delivery simulation models using Python and web apps [version 2; peer review: 3 approved]. NIHR Open Res 2023, 3:48 (https://doi.org/10.3310/nihropenres.13467.2)


This package allows visually appealing, flexible visualisations of discrete event simulations to be created from simpy models, such as the example below:

https://github.com/hsma-programme/Teaching_DES_Concepts_Streamlit/assets/29951987/1adc36a0-7bc0-4808-8d71-2d253a855b31

---

Plotly is leveraged to create the final animation, meaning that users can benefit from the ability to further customise or extend the plotly plot, as well as easily integrating with web frameworks such as Streamlit, Dash or Shiny for Python.

The code has been designed to be flexible and could potentially be used with alternative simulation packages such as ciw or simmer if it is possible to provide all of the required details in the logs that are output.

## Examples

To develop and demonstrate the concept, it has so far been used to incorporate visualisation into several existing simpy models that were not initially designed with this sort of visualisation in mind:
- **a minor injuries unit**, showing the utility of the model at high resolutions with branching pathways and the ability to add in a custom background to clearly demarcate process steps

https://github.com/hsma-programme/Teaching_DES_Concepts_Streamlit/assets/29951987/1adc36a0-7bc0-4808-8d71-2d253a855b31

- **an elective surgical pathway** (with a focus on cancelled theatre slots due to bed unavailability in recovery areas), with length of stay displayed as well as additional text and graphical data

https://github.com/Bergam0t/simpy_visualisation/assets/29951987/12e5cf33-7ce3-4f76-b621-62ab49903113

- **a community mental health assessment pathway**, showing the wait to an appointment as well as highlighting 'urgent' patients with a different icon and showing the time from referral to appointment below the patient icons when they attend the appointment.

https://github.com/Bergam0t/simpy_visualisation/assets/29951987/80467f76-90c2-43db-bf44-41ec8f4d3abd

- **a community mental health assessment pathway with pooling of clinics**, showing the 'home' clinic for clients via icon so the balance between 'home' and 'other' clients can be explored.

https://github.com/Bergam0t/simpy_visualisation/assets/29951987/9f1378f3-1688-4fc1-8603-bd75cfc990fb

- **a community mental health assessment and treatment pathway**, showing the movement of clients between a wait list, a booking list, and returning for repeat appointments over a period of time while sitting on a caseload in between.

https://github.com/Bergam0t/simpy_visualisation/assets/29951987/1cfe48cf-310d-4dc0-bfc2-3c2185e02f0f

# Usage Instructions with SimPy

## Creating a visualisation from an existing model

Two key things need to happen to existing models to work with the visualisation code:
1. All simpy resources need to be changed to simpy stores containing a custom resource with an ID attribute
2. Logging needs to be added at key points: **arrival, (queueing, resource use start, resource use end), departure**
where the steps in the middle can be repeated for as many queues and resource types as required

### 1. All simpy resources need to be changed to simpy stores containing a custom resource with an ID attribute

To allow the use of resources to be visualised correctly - with entities staying with the same resource throughout the time they are using it - it is essential to be able to identify and track individual resources.

By default, this is not possible with Simpy resources. They have no ID attribute or similar.

The easiest workaround which drops fairly painlessly into existing models is to use a simpy store with a custom resource class.

The custom resource is setup as follows:

```{python}
class CustomResource(simpy.Resource):
    def __init__(self, env, capacity, id_attribute=None):
        super().__init__(env, capacity)
        self.id_attribute = id_attribute

    def request(self, *args, **kwargs):
        # Add logic to handle the ID attribute when a request is made
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        # Add logic to handle the ID attribute when a release is made
        return super().release(*args, **kwargs)
```

The creation of simpy resources is then replaced with the following pattern:
```{python}
beds = simpy.Store(environment)

for i in range(number_of_beds):
    beds.put(
        CustomResource(
            environment,
            capacity=1,
            id_attribute=i+1)
        )
```

Instead of requesting a resource in the standard way, you instead use the .get() method.

```{python}
req = beds.get()
```
or
```{python}
with beds.get() as req:
  ...CODE HERE THAT USES THE RESOURCE...
```

At the end, it is important to put the resource back into the store, even if you used the 'with' notation, so it can be made available to the next requester:
```{python}
beds.put(req)
```
This becomes slightly more complex with conditional requesting (for example, where a resource request is made but if it cannot be fulfilled in time, the requester will renege). This is demonstrated in example 3.

The benefit of this is that when we are logging, we can use the `.id_attribute` attribute of the custom resource to record the resource that was in use.
This can have wider benefits for monitoring individual resource utilisation within your model as well.

### 2. Logging needs to be added at key points

The animation function needs to be passed an event log with the following layout:

| patient | pathway  | event_type        | event                    | time | resource_id |
|---------|----------|-------------------|--------------------------|------|-------------|
| 15      | Primary  | arrival_departure | arrival                  | 1.22 |             |
| 15      | Primary  | queue             | enter_queue_for_bed      | 1.35 |             |
| 27      | Revision | arrival_departure | arrival                  | 1.47 |             |
| 27      | Revision | queue             | enter_queue_for_bed      | 1.58 |             |
| 12      | Primary  | resource_use_end  | post_surgery_stay_ends   | 1.9  | 4           |
| 15      | Revision | resource_use      | post_survery_stay_begins | 1.9  | 4           |

One easy way to achieve this is by appending dictionaries to a list at each important point in the process.
For example:

```{python}
event_log = []
...
...
event_log.append(
      {'patient': id,
      'pathway': 'Revision',
      'event_type': 'resource_use',
      'event': 'post_surgery_stay_begins',
      'time': self.env.now,
      'resource_id': bed.id_attribute}
  )
```

The list of dictionaries can then be converted to a panadas dataframe using
```{python}
pd.DataFrame(event_log)
```
and passed to the animation function where required.

#### Event types

Four event types are supported in the model: 'arrival_departure', 'resource_use', 'resource_use_end', and 'queue'.

As a minimum, you will require the use of 'arrival_departure' events and one of
- 'resource_use'/'resource_use_end'
- OR 'queue'

You can also use both 'resource_use' and 'queue' within the same model very effectively (see `ex_1_simplest_case`, `ex_2_branching_and_optional_paths`, and `ex_3_theatres_beds`).

##### arrival_departure

Within this, a minimum of two 'arrival_departure' events per entity are mandatory - `arrival` and `depart`, both with an event_type of `arrival_departure`, as shown below.

```{python}
event_log.append(
      {'patient': unique_entity_identifier,
      'pathway': 'Revision',
      'event_type': 'arrival_departure',
      'event': 'arrival',
      'time': env.now}
  )
```

```{python}
event_log.append(
      {'patient': unique_entity_identifier,
      'pathway': 'Revision',
      'event_type': 'arrival_departure',
      'event': 'depart',
      'time': env.now}
  )
```
These are critical as they are used to determine when patients should first and last appear in the model.
Forgetting to include a departure step for all types of patients can lead to slow model performance as the size of the event logs for individual moments will continue to increase indefinitely.

##### queue

Queues are key steps in the model.

`ex_4_community` and `ex_5_community_follow_up` are examples of models without a step where a simpy resource is used, instead using a booking calendar that determines the time that will elapse between stages for entities.

By tracking each important step in the process as a 'queue' step, the movement of patients can be accurately tracked.

Patients will be ordered by the point at which they are added to the queue, with the first entries appearing at the front (bottom-right) of the queue.

```{python}
event_log.append(
            {'patient': unique_entity_identifier,
             'pathway': 'High intensity',
             'event_type': 'queue',
             'event': 'appointment_booked_waiting',
             'time': self.env.now
             }
        )
```

While the keys shown above are mandatory, you can add as many additional keys to a step's log as desired. This can allow you to flexibly make use of the event log for other purposes as well as the animation.

##### resource_use and resource_use_end

Resource use is more complex to include but comes with two key benefits over the queue:
- it becomes easier to monitor the length of time a resource is in use by a single entity as users won't 'move through' the resource use stage (which can also prove confusing to less experienced viewers)
- it becomes possible to show the total number of resources that are available, making it easier to understand how well resources are being utilised at different stages

```{python}
class CustomResource(simpy.Resource):
    def __init__(self, env, capacity, id_attribute=None):
        super().__init__(env, capacity)
        self.id_attribute = id_attribute

    def request(self, *args, **kwargs):
        # Add logic to handle the ID attribute when a request is made
        # For example, you can assign an ID to the requester
        # self.id_attribute = assign_id_logic()
        return super().request(*args, **kwargs)

    def release(self, *args, **kwargs):
        # Add logic to handle the ID attribute when a release is made
        # For example, you can reset the ID attribute
        # reset_id_logic(self.id_attribute)
        return super().release(*args, **kwargs)

triage = simpy.Store(self.env)

for i in range(n_triage):
    triage.put(
        CustomResource(
            env,
            capacity=1,
            id_attribute = i+1)
        )

# request sign-in/triage
triage_resource = yield triage.get()

event_log.append(
    {'patient': unique_entity_identifier,
     'pathway': 'Trauma',
     'event_type': 'resource_use',
     'event': 'triage_begins',
     'time': env.now,
     'resource_id': triage_resource.id_attribute
    }
)

yield self.env.timeout(1)

event_log.append(
            {'patient': unique_entity_identifier,
             'pathway': 'Trauma',
             'event_type': 'resource_use_end',
             'event': 'triage_complete',
             'time': env.now,
             'resource_id': triage_resource.id_attribute}
        )

# Resource is no longer in use, so put it back in the store
triage.put(triage_resource)
```
When providing your event position details, it then just requires you to include an identifier for the resource.

NOTE: At present this requires you to be using an object to manage your resources. This requirement is planned to be removed in a future version of the work, allowing more flexibility.

```{python}
{'event': 'TRAUMA_stabilisation_begins',
 'x': 300, 'y': 500, 'resource':'n_trauma', 'label': "Being<br>Stabilised" }
```

## Creating the animation

### Determining event positioning in the animation
Once the event log has been created, the positions of each queue and resource must be set up.

An easy way to create this is passing a list of dictionaries to the `pd.DataFrame` function.

The columns required are
`event`: This must match the label used for the event in the event log
`x`: The x coordinate of the event for the animation. This will correspond to the bottom-right hand corner of a queue, or the rightmost resource.
`y`: The y coordinate of the event for the animaation. This will correspond to the lowest row of a queue, or the central point of the resources.
`label`: A label for the stage. This can be hidden at a later step if you opt to use a background image with labels built-in. Note that line breaks in the label can be created using the HTML tag `<br>`.
`resource` (OPTIONAL): Only required if the step is a resource_use step. This looks at the 'scenario' object passed to the `animate_activity_log()` function and pulls the attribute with the given name, which should give the number of available resources for that step.

```{python}
        event_position_df = pd.DataFrame([
                # Triage
                {'event': 'triage_wait_begins',
                 'x':  160, 'y': 400, 'label': "Waiting for<br>Triage"  },
                {'event': 'triage_begins',
                 'x':  160, 'y': 315, 'resource':'n_triage', 'label': "Being Triaged" },

                # Trauma pathway
                {'event': 'TRAUMA_stabilisation_wait_begins',
                 'x': 300, 'y': 560, 'label': "Waiting for<br>Stabilisation" },
                {'event': 'TRAUMA_stabilisation_begins',
                 'x': 300, 'y': 500, 'resource':'n_trauma', 'label': "Being<br>Stabilised" },

                {'event': 'TRAUMA_treatment_wait_begins',
                 'x': 630, 'y': 560, 'label': "Waiting for<br>Treatment" },
                {'event': 'TRAUMA_treatment_begins',
                 'x': 630, 'y': 500, 'resource':'n_cubicles', 'label': "Being<br>Treated" },

                 {'event': 'exit',
                 'x':  670, 'y': 330, 'label': "Exit"}
            ])
```

### Creating the animation
There are two main ways to create the animation:
- using the one-step function `animate_activity_log()` (see pages/1_Simple_ED_interactive, pages/2_Simple_ED_Forced_Overcrowding or pages/3_Complex_ED_Interactive for examples of this)
- using the functions `reshape_for_animations()`, `generate_animation_df()` and `generate_animation()` separately, passing the output of each to the next step (see pages/4_HEP_Orthopaedic_Surgery, pages/5_Community_Booking_Model, or pages/6_Community_Booking_Model_Multistep for examples of this and to get an idea of the extra customisation you can introduce with this approach)

# Acknowledgements

Thanks are due to

- [Dr Daniel Chalk]() for the
- [Professor Tom Monks]() for his extensive materials and teaching on the use of simpy in healthcare and his [material on converting code into packages]()
- [Professor Martin Pitt]() for his tireless work on sharing the importance of visualisation


# Models used as examples

## Emergency department (Treatment Centre) model
Monks.T, Harper.A, Anagnoustou. A, Allen.M, Taylor.S. (2022) Open Science for Computer Simulation

https://github.com/TomMonks/treatment-centre-sim

The layout code for the emergency department model: https://github.com/hsma-programme/Teaching_DES_Concepts_Streamlit

## The hospital efficiency project model
Harper, A., & Monks, T. Hospital Efficiency Project Orthopaedic Planning Model Discrete-Event Simulation [Computer software]. https://doi.org/10.5281/zenodo.7951080

https://github.com/AliHarp/HEP/tree/main

## Simulation model with scheduling example
Monks, T.

https://github.com/health-data-science-OR/stochastic_systems

https://github.com/health-data-science-OR/stochastic_systems/tree/master/labs/simulation/lab5
