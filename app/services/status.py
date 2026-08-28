def derive_ro_status(ro):
    """Auto-derive ReleaseOrder status from all its farmers' statuses."""
    if not ro.farmers:
        return ro.status  # No farmers, keep current status
    
    statuses = set(f.status for f in ro.farmers)
    
    # If all non-disputed farmers are Completed -> Completed
    if statuses <= {'Completed', 'Disputed'} and 'Completed' in statuses:
        return 'Completed'
    # All Completed -> Completed
    if statuses == {'Completed'}:
        return 'Completed'
    # All Disputed -> Disputed
    if statuses == {'Disputed'}:
        return 'Disputed'
    # If any is Started, or mix of Completed and Active/Started/Pending -> In Progress
    if 'Started' in statuses:
        return 'In Progress'
    if 'Completed' in statuses and (statuses & {'Active', 'Started', 'Pending'}):
        return 'In Progress'
    # If any is Active (and not Started) -> Active
    if 'Active' in statuses:
        return 'Active'
    # All Pending, or mix of Pending + Disputed -> Pending
    if statuses <= {'Pending', 'Disputed'}:
        return 'Pending'
    
    return 'Pending'

