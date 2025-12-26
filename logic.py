import random

def generate_assignments(participants):
    """
    Generates a Secret Santa assignment for a list of participants.
    Uses a single-cycle approach to ensure no self-assignments and
    that everyone gives and receives exactly one gift in a closed loop.
    
    :param participants: List of Participant objects
    :return: List of tuples (giver, receiver)
    """
    if len(participants) < 2:
        raise ValueError("Mindestens 2 Teilnehmer sind erforderlich.")

    # Shuffle the participants to create a random order
    shuffled = participants[:]
    random.shuffle(shuffled)
    
    assignments = []
    n = len(shuffled)
    
    for i in range(n):
        giver = shuffled[i]
        # The receiver is the next person in the list, wrapping around to the first
        receiver = shuffled[(i + 1) % n]
        assignments.append((giver, receiver))
        
    return assignments
