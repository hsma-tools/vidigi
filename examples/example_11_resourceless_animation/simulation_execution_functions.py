from examples.example_11_resourceless_animation.model_classes import AssessmentReferralModel

def single_run(args, rep=0):
    '''
    Perform as single run of the model and resturn results as a tuple.
    '''
    model = AssessmentReferralModel(args)
    model.run()
    model.process_run_results()

    return model.results_all, model.results_low, model.results_high, model.event_log
