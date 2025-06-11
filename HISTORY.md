# 1.0.0

Migration guide below!

## Changelog

### BREAKING CHANGES

- significant changes to `VidigiPriorityStore`
    - BREAKING: the original implementation of `VidigiPriorityStore` has been renamed to `VidigiPriorityStoreLegacy`
- default entity column name for all prep and animation functions is now 'entity_id' rather than 'patient'. This can be managed by passing in the argument `entity_col_name="patient"` to each of these functions.
- various classes and functions have been moved into more appropriate files, rather than all existing in `Utils`.
    - VidigiStore, VidigiPriorityStore, VidigiPriorityStoreLegacy and other resources are now in `vidigi.resources`
    - EventLogger is now in `vidigi.logging`
- parameter `icon_and_text_size` has been removed and replaced with separate parameters
    - `resource_icon_size`
    - `entity_icon_size`
    - `text_size`
- parameter `gap_between_rows` has been removed and replaced with separate parameters for queues and resources
    - `gap_between_queue_rows`
    - `gap_between_resource_rows`
- CustomResource is now called VidigiResource. This generally should not cause problems as you are likely to only be accessing it indirectly through use of VidigiStore or VidigiPriorityStore.
- `init_items` argument for VidigiStore and VidigiPriorityStore has been replaced with `num_resources`. Defaulting to none, this functions identically to the `populate_stores` function, but instead allows you to initialise the resource on start.
- the dataframe expected by `generate_animation_df` is now `full_entity_df`, not `full_patient_df`. Only the parameter name needs updating.
- the dataframe expected by `generate_animation` is now `full_entity_df_plus_pos`, not `full_patient_df_plus_pos`. Only the parameter name needs updating.

NEW FEATURES:

Adds

- an additional `VidigiStore` class to replace use of standard store
- tests to ensure identical functioning of VidigiStore, VidigiPriorityStore and VidigiPriorityStoreLegacy to their core simpy counterparts

The benefit of these new classes is that they allow the common resource requesting patterns to be used

So

```python
with self.nurse.request() as req:
    # Freeze the function until the request for a nurse can be met.
    # The patient is currently queuing.
    yield req
```

will work when using a VidigiStore or VidigiPriorityStore - mimicking the syntax of making a request from resources - while supporting the inclusion of a resource ID attribute (not possible with traditional simpy resources) that is necessary to grab for simpy.

To access the attribute, it does necessitate some small change -


```python
with self.nurse.request() as req:
    # Freeze the function until the request for a nurse can be met.
    # The patient is currently queuing.
    nurse_resource = yield req ## NEED TO ASSIGN HERE
```

So
`req.id_attribute` would not work

but

`nurse_resource.id_attribute` would

This is hopefully still a far less substantial change than was required previously, where models using resources had to switch to using `.get()` and `.put()`.

Further testing still required for more complex request logic that incorporates aspects like reneging.

Additional new features:

- allow flexible naming of all key input columns - so you're no longer limited to 'patient', 'event', 'event_type', 'resource_id', 'time', 'pathway'.
    - these are now controlled with the parameters `entity_col_name`, `event_col_name`, `event_type_col_name`,  `resource_col_name", "time_col_name", "pathway_col_name`
- add helper class for event logging (`from vidigi.logging import EventLogger`)
- add helper class and function for generating an event positioning dataframe (`from vidigi.utils import EventPosition, create_event_position_df`)
- add helper function for generating a repeating overlay to the final animation, e.g. to make it clear when something like night or a clinic closure is occurring (`from vidigi.animation import add_repeating_overlay`
- add in a wide range of additional ways that the simulation time can be displayed (e.g. 'Simulation Day 1', am/pm rather than 24 hour, or even custom strftime string)

### BUGFIXES

- fix bugs preventing the generation of 'resourceless' animations
- fix bugs relating to resource wrapping with multiple pools
- prevent shifting of entities to the exit position on the final frame
- fix bug leading to skipped frames when no entities present
- fix bugs with ordering of ciw logs
- fix bug with incorrect end type for resource use in ciw logs
- ensure sim start and end time are respected in different situations
- ensure sensible behaviour when start_time parameter is provided but start_date is not
- ensure exit step always shown

### OTHER

- bump ciw example from 2.x to 3.x
- add more complex ciw example
- add resourceless queue examples
- add multiple concurrent trace example

## 🚀 Migration Guide: `vidigi` 0.0.4 → 1.0.0

This guide will help you update your code and workflows to work with `vidigi` version **1.0.0**, which includes **breaking changes**, **new features**, and **important bug fixes**.

---

### ⚠️ Breaking Changes

#### 1. Default Entity Column Name

**Was:** `'patient'`
**Now:** `'entity_id'`

Update your function calls OR change your entity ID column name to entity_id:

    # Before
    animate_activity_log(event_log,  event_position_df)

    # After
    animate_activity_log(event_log,  event_position_df, entity_col_name="patient")

---

#### 2. Module Reorganization

Some classes and functions have moved:

Old Location | New Location
-------------|--------------
`vidigi.utils.VidigiPriorityStore` | `vidigi.resources.VidigiPriorityStoreLegacy`

Update your import statements accordingly.

---

#### 3. Visual Parameter Changes

- `icon_and_text_size` → replaced with:
    - `resource_icon_size`
    - `entity_icon_size`
    - `text_size`

- `gap_between_rows` → replaced with:
    - `gap_between_queue_rows`
    - `gap_between_resource_rows`

---

#### 4. Parameter names for main dataframes in step-by-step functions

- the dataframe expected by `generate_animation_df` is now `full_entity_df`, not `full_patient_df`. Only the parameter name needs updating.
- the dataframe expected by `generate_animation` is now `full_entity_df_plus_pos`, not `full_patient_df_plus_pos`. Only the parameter name needs updating.

#### 5. `CustomResource` Renamed

`CustomResource` is now `VidigiResource`.
This is typically used indirectly through `VidigiStore` or `VidigiPriorityStore`, so minimal changes may be needed unless you were using it directly.

---

#### 6. Resource Initialization Parameter

`init_items` has been **replaced** with `num_resources` in `VidigiStore` and `VidigiPriorityStore`.

Example:

##### Before

`resource_store = VidigiStore(simulation_env, init_items=[...])`

OR

`resource_store = simpy.Store(simulation_env)`

`populate_store(5, resource_store, simulation_env)`

##### After

`resource_store = VidigiStore(simulation_env, num_resources=3)`

---

### ✨ New Features

#### ✅ Flexible Column Names

You can now customize column names in the animation and animation prep functions, meaning you are no longer tied to using 'patient' for your entity IDs!

- `entity_col_name`
- `event_col_name`
- `event_type_col_name`
- `resource_col_name`
- `time_col_name`
- `pathway_col_name`

Defaults are

- entity_id
- event
- event_type
- resource_id
- time
- pathway

(note 'pathway' is an optional column you may choose not to populate)


### ✅ What You Should Do

- [ ] Update your column name to 'entity_id' instead of 'patient' or pass overrides in the form of 'entity_col_name="patient"`
- [ ] Update import paths
- [ ] Update parameter names for the main dataframe in `generate_animation_df` and `generation_animation` (if using the step-by-step animation functions instead of the all-in-one)
- [ ] Switch from VidigiPriorityStore to VidigiPriorityStoreLegacy if you don't want to have to make any changes to how you request resources
- [ ] Replace removed sizing and spacing parameters with new ones
- [ ] Explore new features and examples - the new resource types, event logging helpers and event positioning helpers may make your life easier!

---

If you run into issues or have questions, check out the documentation or open an issue on the repo. Thanks for upgrading!
