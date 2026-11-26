from app.services.account_service import run_export_job


def handle_account_export(db, job) -> None:
    """Job kind 'account_export'. Payload: {export_id}. Builds the user's data archive; the owner is notified when it is ready."""
    run_export_job(db, int(job.payload["export_id"]))
