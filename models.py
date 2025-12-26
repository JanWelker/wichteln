from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Round(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    participants = db.relationship('Participant', backref='round', lazy=True)
    assignments = db.relationship('Assignment', backref='round', lazy=True)

class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    round_id = db.Column(db.Integer, db.ForeignKey('round.id'), nullable=False)

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    round_id = db.Column(db.Integer, db.ForeignKey('round.id'), nullable=False)
    giver_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=False)

    giver = db.relationship('Participant', foreign_keys=[giver_id])
    receiver = db.relationship('Participant', foreign_keys=[receiver_id])
