# vidigi (Visual Interactive Dynamics and Integrated Graphical Insights)

[<img src="https://img.shields.io/pypi/v/vidigi?label=pypi%20package">](https://pypi.org/project/vidigi/)
[![DOI](https://zenodo.org/badge/888169040.svg)](https://doi.org/10.5281/zenodo.14635602)
[![All Contributors](https://img.shields.io/github/all-contributors/hsma-tools/vidigi?color=ee8449&style=flat-square)](#contributors)

---

Welcome to vidigi - a package for visualising real or simulated pathways.

vidigi is the Esperanto for 'to show'

(or it's the backronym 'Visual Interactive Dynamics and Integrated Graphical Insights' - whichever floats your boat)

https://github.com/hsma-programme/Teaching_DES_Concepts_Streamlit/assets/29951987/1adc36a0-7bc0-4808-8d71-2d253a855b31

Primarily developed for healthcare simulation and intended to allow easy integration with tools like Streamlit so users can see the impact of changes to simulation parameters in real-time, vidigi handles the conversion of your simulation event logs into engaging and flexible animations.

With just a minimal set of logs - with helper functions provided to make that easier than ever to integrate into existing SimPy or Ciw simulations - you can start generating and customising your visualisations in minutes.

## Getting started

Head to the [documentation](https://hsma-tools.github.io/vidigi/vidigi_docs/) to find out how to create an animated version of your model.

You can install vidigi from PyPi with the command `pip install vidigi`.

## Introduction

Visual display of the outputs of discrete event simulations in simpy have been identified as one of the limitations of simpy, potentially hindering adoption of FOSS simulation in comparison to commercial modelling offerings or GUI FOSS alternatives such as JaamSim.

> When compared to commercial DES software packages that are commonly used in health research, such as Simul8, or AnyLogic, a limitation of our approach is that we do not display a dynamic patient pathway or queuing network that updates as the model runs a single replication. This is termed Visual Interactive Simulation (VIS) and can help users understand where process problems and delays occur in a patient pathway; albeit with the caveat that single replications can be outliers. A potential FOSS solution compatible with a browser-based app could use a Python package that can represent a queuing network, such as NetworkX, and displaying results via matplotlib. If sophisticated VIS is essential for a FOSS model then researchers may need to look outside of web apps; for example, salabim provides a powerful FOSS solution for custom animation of DES models.
> -  Monks T and Harper A. Improving the usability of open health service delivery simulation models using Python and web apps [version 2; peer review: 3 approved]. NIHR Open Res 2023, 3:48 (https://doi.org/10.3310/nihropenres.13467.2)

This package allows visually appealing, flexible visualisations of the movement of entities through some kind of pathway.

It is primarily tested with discrete event simulations to be created from SimPy and Ciw models, though could be used with other simulation libraries or real-world data.

Plotly is leveraged to create the final animation, meaning that users can benefit from the ability to further customise or extend the plotly plot, as well as easily integrating with web frameworks such as Streamlit, Dash or Shiny for Python.

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

# Test Coverage

Vidigi is still in relatively early development, with test coverage being limited. More tests are being written all the time - but for now, please continue to sense-check your outputs!

Fancy helping out? Consider submitting a pull request with some tests! It's a great way to get to know the codebase better.

## Animation Functions

![](https://img.shields.io/badge/vidigi.animation.animate__activity__log()-Not%20covered-orange?style=for-the-badge&logo=pytest)
![](https://img.shields.io/badge/vidigi.animation.generate__animation()-Not%20covered-orange?style=for-the-badge&logo=pytest)
![](https://img.shields.io/badge/vidigi.prep.generation__animation__df()-Not%20covered-orange?style=for-the-badge&logo=pytest)
![](https://img.shields.io/badge/vidigi.prep.reshape__for__animation-Partially%20Covered-f6d661?style=for-the-badge&logo=pytest)

## Resource Classes and Helper Functions

![](https://img.shields.io/badge/vidigi.resources.CustomResource-Good%20Coverage-7ff661?style=for-the-badge&logo=pytest)
![](https://img.shields.io/badge/vidigi.resources.VidigiStore-Good%20Coverage-7ff661?style=for-the-badge&logo=pytest)
![](https://img.shields.io/badge/vidigi.resources.VidigiPriorityStore-Good%20Coverage-7ff661?style=for-the-badge&logo=pytest)
![](https://img.shields.io/badge/vidigi.resources.populate__store()-Good%20Coverage-7ff661?style=for-the-badge&logo=pytest)

## Logging Classes and Helpers
![](https://img.shields.io/badge/vidigi.logger.EventLogger-Not%20Covered-orange?style=for-the-badge&logo=pytest)
![](https://img.shields.io/badge/vidigi.logger.TrialLogger-Not%20Covered-orange?style=for-the-badge&logo=pytest)
![](https://img.shields.io/badge/vidigi.ciw.event__log__from__ciw__recs()-Not%20Covered-orange?style=for-the-badge&logo=pytest)

## Event Positioning Helpers
![](https://img.shields.io/badge/vidigi.utils.EventPosition-Not%20Covered-orange?style=for-the-badge&logo=pytest)
![](https://img.shields.io/badge/vidigi.utils.create__event__position__df()-Not%20Covered-orange?style=for-the-badge&logo=pytest)


# Acknowledgements

Thanks are due to

- [Dr Daniel Chalk](https://github.com/hsma-chief-elf) for support and simpy training on the HSMA programme
- [Professor Tom Monks](https://github.com/TomMonks) for his extensive materials and teaching on the use of simpy in healthcare and his [material on converting code into packages](https://www.pythonhealthdatascience.com/content/03_mgt/03_mgt_front_page.html)
- [Helena Robinson](https://github.com/helenajr) for testing and bugfinding

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


# Contributors

Thanks goes to all of the following people ([emoji key](https://allcontributors.org/docs/en/emoji-key)).


<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://www.linkedin.com/in/amyheather"><img src="https://avatars.githubusercontent.com/u/92166537?v=4?s=100" width="100px;" alt="Amy Heather"/><br /><sub><b>Amy Heather</b></sub></a><br /><a href="#doc-amyheather" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="http://hsma.co.uk"><img src="https://avatars.githubusercontent.com/u/29951987?v=4?s=100" width="100px;" alt="Sammi Rosser"/><br /><sub><b>Sammi Rosser</b></sub></a><br /><a href="#code-Bergam0t" title="Code">💻</a> <a href="#doc-Bergam0t" title="Documentation">📖</a> <a href="#test-Bergam0t" title="Tests">⚠️</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/helenajr"><img src="https://avatars.githubusercontent.com/u/63923671?v=4?s=100" width="100px;" alt="Helena Robinson"/><br /><sub><b>Helena Robinson</b></sub></a><br /><a href="#bug-helenajr" title="Bug reports">🐛</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->

Contributors of any kind - not just code - are welcome! Please see `CONTRIBUTING.md` for guidance.
