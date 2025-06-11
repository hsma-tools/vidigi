import ciw

# From https://ciw.readthedocs.io/en/latest/Tutorial/tutorial_ii.html

N = ciw.create_network(

    arrival_distributions=[ciw.dists.Exponential(rate=0.3 / 60),

                           ciw.dists.Exponential(rate=0.2 / 60),

                           None],

    service_distributions=[ciw.dists.Exponential(rate=2.0 / 60),

                           ciw.dists.Exponential(rate=1.4 / 60),

                           ciw.dists.Exponential(rate=1.0 / 60)],

    routing=[[0.0, 0.3, 0.7],

             [0.0, 0.0, 1.0],

             [0.0, 0.0, 0.0]],

    number_of_servers=[1, 2, 2]

)
