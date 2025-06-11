from examples.example_12_resourceless_with_back_and_forth.model_classes import AssessmentReferralModel

def single_run(args, rep=0):
    '''
    Perform as single run of the model and resturn results as a tuple.
    '''
    model = AssessmentReferralModel(args)
    model.run()
    model.process_run_results()

    return model.results_all, model.results_low, model.results_high, model.event_log, model.bookings, model.available_slots, model.daily_caseload_snapshots, model.daily_waiting_for_booking_snapshots, model.results_daily_arrivals
