from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from datetime import timedelta

db = SQLAlchemy()

class Job(db.Model):
    __tablename__ = 'jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    responsibilities = db.Column(db.Text, nullable=False)
    requirements = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    applicants = db.relationship('Applicant', backref='job', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'requirements': self.requirements,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat()
        }

class Applicant(db.Model):
    __tablename__ = 'applicants'
    
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20))
    cv_file_path = db.Column(db.String(500))
    cv_text_content = db.Column(db.Text)
    birth_date = db.Column(db.Date)
    age = db.Column(db.Integer)
    education = db.Column(db.String(100))
    school_name = db.Column(db.String(255))
    major = db.Column(db.String(255))
    has_experience = db.Column(db.String(10))
    company_name = db.Column(db.String(255))
    position = db.Column(db.String(255))
    work_start = db.Column(db.Date)
    work_end = db.Column(db.Date)
    work_duration = db.Column(db.String(100))
    still_working = db.Column(db.String(10))
    applied_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @property
    def applied_at_local(self):
        return self.applied_at + timedelta(hours=7)

    # Relationships
    screening_result = db.relationship('ScreeningResult', backref='applicant', uselist=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'job_id': self.job_id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'applied_at': self.applied_at.isoformat()
        }

class Admin(UserMixin, db.Model):
    __tablename__ = 'admins'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScreeningResult(db.Model):
    __tablename__ = 'screening_results'

    id = db.Column(db.Integer, primary_key=True)
    applicant_id = db.Column(
        db.Integer,
        db.ForeignKey('applicants.id', ondelete='CASCADE'),
        nullable=False,
        unique=True
    )

    similarity_score = db.Column(db.Float, default=0.0)
    final_decision = db.Column(db.String(50))
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScreeningConfig(db.Model):
    __tablename__ = 'screening_config'

    id = db.Column(db.Integer, primary_key=True)

    recommended_threshold = db.Column(
        db.Float,
        default=0.6
    )