import os
import logging
from flask import Flask, render_template, request, redirect, url_for, flash
from models import db, Round, Participant, Assignment
from logic import generate_assignments

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///local.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'secret-santa-dev-key'

db.init_app(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        round_name = request.form.get('name')
        if round_name:
            new_round = Round(name=round_name)
            db.session.add(new_round)
            db.session.commit()
            return redirect(url_for('view_round', round_id=new_round.id))
    
    rounds = Round.query.order_by(Round.created_at.desc()).all()
    return render_template('index.html', rounds=rounds)

@app.route('/round/<int:round_id>', methods=['GET', 'POST'])
def view_round(round_id):
    round_obj = Round.query.get_or_404(round_id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        if name and email:
            p = Participant(name=name, email=email, round_id=round_obj.id)
            db.session.add(p)
            db.session.commit()
            return redirect(url_for('view_round', round_id=round_id))

    return render_template('round.html', round=round_obj)

@app.route('/round/<int:round_id>/assign', methods=['POST'])
def assign(round_id):
    round_obj = Round.query.get_or_404(round_id)
    
    # Check if assignments already exist
    if round_obj.assignments:
        flash("Zuweisungen existieren bereits!", "warning")
        return redirect(url_for('view_round', round_id=round_id))

    participants = round_obj.participants
    try:
        pairs = generate_assignments(participants)
        
        for giver, receiver in pairs:
            assignment = Assignment(round_id=round_id, giver_id=giver.id, receiver_id=receiver.id)
            db.session.add(assignment)
            
            # Simulate sending email
            logger.info(f"EMAIL SIMULATION: To {giver.email}: You must buy a gift for {receiver.name}!")
            
        db.session.commit()
        flash("Die Wichtel wurden erfolgreich zugewiesen! (Emails simuliert)", "success")
    
    except ValueError as e:
        flash(str(e), "danger")
        
    return redirect(url_for('view_round', round_id=round_id))

@app.route('/round/<int:round_id>/reset', methods=['POST'])
def reset_round(round_id):
    # Keep participants, delete assignments
    Assignment.query.filter_by(round_id=round_id).delete()
    db.session.commit()
    flash("Zuweisungen wurden zurückgesetzt.", "info")
    return redirect(url_for('view_round', round_id=round_id))

if __name__ == '__main__':
    with app.app_context():
        # Wait for DB in docker logic usually handled by entrypoint or retry loop, 
        # but Flask dev server simplifies this.
        # Create tables if they don't exist
        try:
            db.create_all()
        except Exception as e:
            logger.error(f"Error creating DB tables (might be waiting for DB start): {e}")
            
    app.run(host='0.0.0.0', port=5000)
