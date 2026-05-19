from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from utils.text_processing import smart_extract_text, clean_cv_text
from models.database import db, Job, Applicant, Admin, ScreeningResult
from datetime import datetime, timedelta
import pandas as pd
import io
import os
import uuid
import threading
from config import Config
from sqlalchemy import text
from functools import wraps
from flask import session

# Cache control decorator
def no_cache(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        response = make_response(f(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    return decorated_function

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    db.init_app(app)
    
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'admin_login'
    login_manager.login_message_category = 'info'
    
    @login_manager.user_loader
    def load_user(user_id):
        return Admin.query.get(int(user_id))
    
    # Helper functions
    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'
    
    def save_uploaded_file(file):
        if file and allowed_file(file.filename):
            upload_folder = app.config['UPLOAD_FOLDER']
            os.makedirs(upload_folder, exist_ok=True)
            
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4()}.{ext}"
            file_path = os.path.join(upload_folder, filename)
            
            file.save(file_path)
            return file_path
        return None
    
    # ===== PERBAIKAN: Gunakan screening_result bukan screening_results =====
    def process_applicant_screening(applicant_id, job_text, cv_text):
        try:
            from utils.similarity_calculators import perform_screening

            results = perform_screening(job_text, cv_text)

            screening = ScreeningResult.query.filter_by(
                applicant_id=applicant_id
            ).first()

            if not screening:
                screening = ScreeningResult(applicant_id=applicant_id)

            screening.similarity_score = results['score']
            screening.final_decision = results['decision']
            screening.processed_at = datetime.now()

            return screening, True

        except Exception as e:
            print(f"❌ Screening error: {e}")
            return None, False

    # ===== PUBLIC ROUTES =====
    @app.route('/')
    def index():
        jobs = Job.query.filter_by(is_active=True).order_by(Job.created_at.desc()).all()
        return render_template('index.html', jobs=jobs)
    
    @app.route('/apply/<int:job_id>', methods=['GET', 'POST'])
    def apply_job(job_id):
        job = Job.query.get_or_404(job_id)

        if request.method == 'POST':
            name = request.form.get('name')
            email = request.form.get('email')
            phone = request.form.get('phone')
            birth_date = request.form.get('birth_date')
            age = request.form.get('age')
            education = request.form.get('education')
            school_name = request.form.get('school_name')
            major = request.form.get('major')
            has_experience = request.form.get('has_experience')
            company_name = request.form.get('company_name')
            position = request.form.get('position')
            work_start = request.form.get('work_start')
            work_end = request.form.get('work_end')
            work_duration = request.form.get('work_duration')
            still_working = request.form.get(
                'still_working',
                'no'
            )
            cv_file = request.files.get('cv')

            if not all([name, email, cv_file]):
                flash('Harap isi semua field wajib.', 'error')
                return redirect(request.url)

            cv_file_path = save_uploaded_file(cv_file)
            if not cv_file_path:
                flash('Upload CV gagal.', 'error')
                return redirect(request.url)

            # === EXTRACT & CLEAN CV ===
            try:
                cv_text = smart_extract_text(cv_file_path)

                if not cv_text or len(cv_text.strip()) < 30:
                    raise ValueError("CV text terlalu pendek atau gagal diekstrak")

            except Exception:
                if os.path.exists(cv_file_path):
                    os.remove(cv_file_path)

                flash(
                    'CV tidak dapat dibaca. Pastikan file berupa PDF dengan teks yang bisa disalin.',
                    'error'
                )
                return redirect(request.url)

            # === SIMPAN APPLICANT ===
            applicant = Applicant(
            job_id=job_id,
            name=name,
            email=email,
            phone=phone,
            birth_date=datetime.strptime(
                birth_date,
                '%Y-%m-%d'
            ).date() if birth_date else None,
            age=int(age) if age else None,
            education=education,
            school_name=school_name,
            major=major,
            has_experience=has_experience,
            company_name=company_name,
            position=position,
            work_start=datetime.strptime(
                work_start,
                '%Y-%m-%d'
            ).date() if work_start else None,
            work_end=datetime.strptime(
                work_end,
                '%Y-%m-%d'
            ).date() if work_end else None,
            work_duration=work_duration,
            still_working=still_working if still_working else 'no',
            cv_file_path=cv_file_path,
            cv_text_content=cv_text
        )

            db.session.add(applicant)
            db.session.commit()

            # === SIAPKAN JOB TEXT ===
            job_text = clean_cv_text(
                f"{job.title}. {job.description}. {job.responsibilities}. {job.requirements}"
            )

            # === BACKGROUND SCREENING ===
            def run_screening():
                with app.app_context():
                    try:
                        from utils.similarity_calculators import perform_screening

                        # 🔥 PENTING: reset session biar aman di thread
                        db.session.remove()

                        results = perform_screening(job_text, cv_text)

                        screening = ScreeningResult.query.filter_by(
                            applicant_id=applicant.id
                        ).first()

                        if not screening:
                            screening = ScreeningResult(applicant_id=applicant.id)

                        screening.similarity_score = results['score']
                        screening.final_decision = results['decision']
                        screening.processed_at = datetime.now()

                        db.session.add(screening)
                        db.session.commit()

                    except Exception as e:
                        print(f"❌ Thread screening error: {e}")
                        db.session.rollback()

                    finally:
                        db.session.remove()  # 🔥 bersihin lagi setelah selesai

            threading.Thread(target=run_screening).start()

            return redirect(url_for('application_success', applicant_id=applicant.id))

        return render_template('apply.html', job=job)
    
    @app.route('/application-success/<int:applicant_id>')
    def application_success(applicant_id):
        applicant = Applicant.query.get_or_404(applicant_id)
        return render_template('application_success.html', applicant=applicant)
    
    # ===== ADMIN ROUTES =====
    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if current_user.is_authenticated:
            return redirect(url_for('admin_dashboard'))
            
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            
            print(f"🔐 LOGIN ATTEMPT: username='{username}', password='{password}'")
            
            admin = Admin.query.filter_by(username=username).first()
            
            # AUTO-CREATE ADMIN IF NOT EXISTS
            if not admin and username == 'admin':
                print("⚠️  Admin not found, creating new admin...")
                admin = Admin(
                    username='admin',
                    password='password',
                    email='admin@cv-screening.com'
                )
                db.session.add(admin)
                db.session.commit()
                print("✅ New admin created with password: 'password'")
                admin = Admin.query.filter_by(username='admin').first()

            if admin and admin.password == password:
                login_user(admin)
                flash('Login berhasil!', 'success')
                session['from_login'] = True   # ← TAMBAHIN INI
                return redirect(url_for('admin_dashboard'))

            else:
                flash('Login gagal!', 'error')
                return redirect(url_for('admin_login'))
        
        return render_template('admin/login.html')
    
    @app.route('/admin/logout')
    @login_required
    @no_cache
    def admin_logout():
        logout_user()
        flash('Anda telah logout.', 'info')
        session['from_login'] = True
        return redirect(url_for('admin_login'))
    
    @app.route('/admin/dashboard')
    @login_required
    @no_cache
    def admin_dashboard():
        # Statistics
        total_applicants = Applicant.query.count()
        total_jobs = Job.query.count()
        active_jobs = Job.query.filter_by(is_active=True).count()
        
        # Recent applicants (last 30 days)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        recent_applicants = Applicant.query.filter(
            Applicant.applied_at >= thirty_days_ago
        ).count()
        
        # Screening statistics - PERBAIKI: pakai screening_result
        recommended_count = db.session.query(ScreeningResult).filter_by(
            final_decision='recommended'
        ).count()

        not_recommended_count = db.session.query(ScreeningResult).filter_by(
            final_decision='not_recommended'
        ).count()
       
        # Recent applicants for table
        recent_applicants_list = Applicant.query.order_by(
            Applicant.applied_at.desc()
        ).limit(10).all()
        
        return render_template('admin/dashboard.html', 
                             total_applicants=total_applicants,
                             total_jobs=total_jobs,
                             active_jobs=active_jobs,
                             recent_applicants=recent_applicants,
                             recommended_count=recommended_count,
                             not_recommended_count=not_recommended_count,
                             recent_applicants_list=recent_applicants_list)

    # ===== API ROUTES FOR CHARTS =====
    @app.route('/api/dashboard/stats')
    @login_required
    @no_cache
    def api_dashboard_stats():
        # Monthly applicants (last 6 months)
        six_months_ago = datetime.now() - timedelta(days=180)
        
        monthly_stats = db.session.query(
            db.func.date_format(Applicant.applied_at, '%Y-%m').label('month'),
            db.func.count(Applicant.id).label('count')
        ).filter(Applicant.applied_at >= six_months_ago)\
         .group_by('month')\
         .order_by(db.desc('month'))\
         .limit(6)\
         .all()
        
        monthly_stats = [{'month': m.month, 'count': m.count} for m in monthly_stats]
        
        # Applications by job
        job_stats = db.session.query(
            Job.title.label('job'),
            db.func.count(Applicant.id).label('count')
        ).join(Applicant, Job.id == Applicant.job_id)\
         .group_by(Job.title)\
         .all()
        
        job_stats = [{'job': j.job, 'count': j.count} for j in job_stats]
        
        return jsonify({
            'monthly_applicants': monthly_stats,
            'job_distribution': job_stats
        })
    
    # ===== API ROUTE UNTUK SCREENING DETAIL =====
    @app.route('/api/screening/stats')
    @login_required
    def api_screening_stats():
        """Statistik hasil screening untuk dashboard"""

        # Distribusi keputusan
        decisions = db.session.query(
            ScreeningResult.final_decision,
            db.func.count(ScreeningResult.id)
        ).group_by(ScreeningResult.final_decision).all()

        # Distribusi skor similarity (MiniLM)
        scores = db.session.query(
            db.func.round(ScreeningResult.similarity_score, 1).label('score_range'),
            db.func.count(ScreeningResult.id).label('count')
        ).filter(ScreeningResult.similarity_score.isnot(None)) \
        .group_by('score_range') \
        .order_by('score_range') \
        .all()

        # Rata-rata similarity score
        similarity_avg = db.session.query(
            db.func.avg(ScreeningResult.similarity_score)
        ).filter(ScreeningResult.similarity_score.isnot(None)).scalar()

        return jsonify({
            'decision_distribution': dict(decisions),
            'score_distribution': [
                {'score': float(s.score_range), 'count': s.count}
                for s in scores
            ],
            'average_similarity_score': float(similarity_avg) if similarity_avg else 0
        })

    
    # ===== APPLICANTS ROUTE =====
    @app.route('/admin/applicants')
    @login_required
    @no_cache
    def admin_applicants():
        # Get query parameters
        page = request.args.get('page', 1, type=int)
        job_filter = request.args.get('job_filter', '')
        search = request.args.get('search', '')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')

        query = Applicant.query.join(ScreeningResult)
        
        if job_filter:
            query = query.filter(Applicant.job_id == job_filter)\
                .order_by(ScreeningResult.similarity_score.desc())
            
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (Applicant.name.ilike(search_term)) | 
                (Applicant.email.ilike(search_term))
            )
        
        if start_date:
            try:
                start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(Applicant.applied_at >= start_datetime)
            except ValueError:
                flash('Format tanggal mulai tidak valid.', 'warning')
        
        if end_date:
            try:
                end_datetime = datetime.strptime(end_date, '%Y-%m-%d')
                end_datetime = end_datetime + timedelta(days=1)
                query = query.filter(Applicant.applied_at < end_datetime)
            except ValueError:
                flash('Format tanggal akhir tidak valid.', 'warning')

        applicants = Applicant.query.order_by(Applicant.applied_at.desc()).all()
        
        # Get screening results
        applicant_ids = [app.id for app in applicants]
        screening_results = {}
        
        if applicant_ids:
            results = ScreeningResult.query.filter(
                ScreeningResult.applicant_id.in_(applicant_ids)
            ).all()
            
            for result in results:
                screening_results[result.applicant_id] = result
        
        jobs = Job.query.all()
        
        return render_template('admin/applicants.html', 
                            applicants=applicants,
                            jobs=jobs,
                            job_filter=job_filter,
                            search=search,
                            screening_results=screening_results,
                            start_date=start_date, 
                            end_date=end_date)
    
    @app.route('/admin/jobs')
    @login_required
    @no_cache
    def admin_jobs():
        search = request.args.get('search', '')
        status = request.args.get('status')  # ← TARUH DI SINI

        query = Job.query

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                (Job.title.ilike(search_term)) |
                (Job.description.ilike(search_term))
            )

        if status:  # ← TARUH DI SINI
            query = query.filter(Job.is_active == (status == 'active'))

        jobs = query.order_by(Job.created_at.desc()).all()

        return render_template(
            'admin/jobs.html',
            jobs=jobs,
            search=search,
            status=status
        )

    @app.route('/admin/jobs/create', methods=['GET', 'POST'])
    @login_required
    @no_cache
    def admin_create_job():
        if request.method == 'POST':
            title = request.form.get('title')
            description = request.form.get('description')
            responsibilities = request.form.get('responsibilities')
            requirements = request.form.get('requirements')
            is_active = 'is_active' in request.form
            
            if not all([title, description, requirements]):
                flash('Harap isi semua field yang wajib.', 'error')
                return redirect(request.url)

            job = Job(
                title=title,
                description=description,
                responsibilities=responsibilities,
                requirements=requirements,
                is_active=is_active
            )
            
            db.session.add(job)
            db.session.commit()
            
            flash('Lowongan berhasil dibuat!', 'success')
            return redirect(url_for('admin_jobs'))
        
        return render_template('admin/job_form.html')
    
    @app.route('/admin/jobs/edit/<int:job_id>', methods=['GET', 'POST'])
    @login_required
    @no_cache
    def admin_edit_job(job_id):
        job = Job.query.get_or_404(job_id)
        
        if request.method == 'POST':
            job.title = request.form.get('title')
            job.description = request.form.get('description')
            job.responsibilities = request.form.get('responsibilities')
            job.requirements = request.form.get('requirements')
            job.is_active = 'is_active' in request.form
            
            db.session.commit()
            
            flash('Lowongan berhasil diupdate!', 'success')
            return redirect(url_for('admin_jobs'))
        
        return render_template('admin/job_form.html', job=job)
    
    @app.route('/admin/jobs/delete/<int:job_id>', methods=['POST'])
    @login_required
    @no_cache
    def admin_delete_job(job_id):
        job = Job.query.get_or_404(job_id)
        
        if job.applicants:
            flash('Tidak bisa menghapus lowongan yang sudah memiliki pelamar.', 'error')
            return redirect(url_for('admin_jobs'))
        
        db.session.delete(job)
        db.session.commit()
        
        flash('Lowongan berhasil dihapus!', 'success')
        return redirect(url_for('admin_jobs'))
    
    @app.route('/admin/applicant/<int:applicant_id>')
    @login_required
    @no_cache
    def admin_view_applicant(applicant_id):
        applicant = Applicant.query.get_or_404(applicant_id)
        screening_result = ScreeningResult.query.filter_by(
            applicant_id=applicant_id
        ).first()
        
        return render_template('admin/view_applicant.html',
                             applicant=applicant,
                             screening_result=screening_result)
    
    # ===== SCREENING PROCESSING ROUTES =====
    @app.route('/admin/process-screening/<int:applicant_id>', methods=['POST'])
    @login_required
    def process_screening(applicant_id):
        """Manual trigger untuk screening"""
        applicant = Applicant.query.get_or_404(applicant_id)
        
        try:
            job = applicant.job
            if not job:
                flash('Job tidak ditemukan', 'error')
                return redirect(url_for('admin_view_applicant', applicant_id=applicant_id))
            
            job_text = clean_cv_text(
                f"{job.title}. {job.description}. {job.responsibilities}. {job.requirements}"
            )
            cv_text = applicant.cv_text_content or ""
            
            screening, success = process_applicant_screening(applicant_id, job_text, cv_text)
            
            if screening and success:
                db.session.add(screening)
                db.session.commit()
                flash('Screening berhasil diproses!', 'success')
            else:
                flash('Gagal memproses screening', 'error')
                
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
        
        return redirect(url_for('admin_view_applicant', applicant_id=applicant_id))
    
    @app.route('/admin/batch-process-screening', methods=['POST'])
    @login_required
    def batch_process_screening():
        """Process screening for multiple applicants"""
        try:
            applicants = Applicant.query.all()
            processed = 0
            errors = 0
            
            for applicant in applicants:
                try:
                    job = applicant.job
                    if not job:
                        errors += 1
                        continue
                    
                    job_text = clean_cv_text(
                        f"{job.title}. {job.description}. {job.responsibilities}. {job.requirements}"
                    )
                    cv_text = applicant.cv_text_content or ""
                    
                    if not cv_text or len(cv_text.strip()) < 10:
                        errors += 1
                        continue
                    
                    screening, success = process_applicant_screening(applicant.id, job_text, cv_text)
                    
                    if screening and success:
                        db.session.add(screening)
                        processed += 1
                    
                except Exception as e:
                    errors += 1
            
            db.session.commit()
            
            if errors > 0:
                flash(f'Berhasil memproses {processed} pelamar, {errors} error.', 'warning')
            else:
                flash(f'Berhasil memproses {processed} pelamar!', 'success')
                
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
        
        return redirect(url_for('admin_applicants'))
    
    @app.route('/admin/applicants/delete/<int:applicant_id>', methods=['POST'])
    @login_required
    def admin_delete_applicant(applicant_id):
        """Delete an applicant"""
        applicant = Applicant.query.get_or_404(applicant_id)
        
        try:
            # Delete screening result
            screening = ScreeningResult.query.filter_by(applicant_id=applicant_id).first()
            if screening:
                db.session.delete(screening)
            
            # Delete CV file
            if applicant.cv_file_path and os.path.exists(applicant.cv_file_path):
                try:
                    os.remove(applicant.cv_file_path)
                except:
                    pass
            
            db.session.delete(applicant)
            db.session.commit()
            
            flash('Pelamar berhasil dihapus!', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
        
        return redirect(url_for('admin_applicants'))
    
    @app.route('/admin/update-decision/<int:applicant_id>', methods=['POST'])
    @login_required
    def admin_update_decision(applicant_id):
        """Manually update screening decision"""
        new_decision = request.form.get('decision')
        
        if not new_decision or new_decision not in ['recommended', 'not_recommended']:
            flash('Keputusan tidak valid!', 'error')
            return redirect(url_for('admin_view_applicant', applicant_id=applicant_id))
        
        try:
            screening = ScreeningResult.query.filter_by(applicant_id=applicant_id).first()
            if not screening:
                screening = ScreeningResult(applicant_id=applicant_id)
            
            screening.final_decision = new_decision
            screening.processed_at = datetime.now()
            db.session.add(screening)
            db.session.commit()
            
            flash('Keputusan berhasil diupdate!', 'success')
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
        
        return redirect(url_for('admin_view_applicant', applicant_id=applicant_id))
    
    # ===== download cv =====
    @app.route('/admin/download-cv/<int:applicant_id>')
    @login_required
    def download_cv(applicant_id):
        applicant = Applicant.query.get_or_404(applicant_id)

        if not applicant.cv_file_path or not os.path.exists(applicant.cv_file_path):
            flash('File CV tidak ditemukan.', 'error')
            return redirect(url_for('admin_view_applicant', applicant_id=applicant_id))

        return send_file(
            applicant.cv_file_path,
            as_attachment=True
        )
    
   # ===== view cv =====
    @app.route('/admin/view-cv/<int:applicant_id>')
    @login_required
    def view_cv(applicant_id):
        applicant = Applicant.query.get_or_404(applicant_id)

        if not applicant.cv_file_path or not os.path.exists(applicant.cv_file_path):
            flash('File CV tidak ditemukan.', 'error')
            return redirect(url_for('admin_view_applicant', applicant_id=applicant_id))

        return send_file(
            applicant.cv_file_path,
            mimetype='application/pdf'
        )
    
    # ===== THRESHOLD SETTINGS =====
    @app.route('/admin/threshold', methods=['GET', 'POST'])
    @login_required
    @no_cache
    def screening_settings():

        from models.database import ScreeningConfig

        # Ambil config pertama
        config = ScreeningConfig.query.first()

        # Kalau belum ada, buat default
        if not config:
            config = ScreeningConfig(
                recommended_threshold=0.6
            )

            db.session.add(config)
            db.session.commit()

        # SAVE SETTING
        if request.method == 'POST':

            try:
                recommended = float(
                    request.form.get('recommended_threshold')
                )

                config.recommended_threshold = recommended

                db.session.commit()

                flash(
                    'Threshold berhasil diperbarui!',
                    'success'
                )

                return redirect(url_for('screening_settings'))

            except Exception as e:

                db.session.rollback()

                flash(
                    f'Gagal update threshold: {str(e)}',
                    'error'
                )

        return render_template(
            'admin/threshold.html',
            config=config
        )
   
    # ===== APPLICANT SUMMARY PDF =====
    @app.route('/admin/applicant-summary/<int:applicant_id>')
    @login_required
    @no_cache
    def generate_applicant_summary_pdf(applicant_id):

        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle
        )

        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors

        from PyPDF2 import PdfMerger

        import tempfile

        applicant = Applicant.query.get_or_404(applicant_id)

        screening_result = ScreeningResult.query.filter_by(
            applicant_id=applicant.id
        ).first()

        # TEMP FILES
        summary_temp = tempfile.NamedTemporaryFile(
            delete=False,
            suffix='.pdf'
        )

        merged_temp = tempfile.NamedTemporaryFile(
            delete=False,
            suffix='.pdf'
        )

        # PDF DOCUMENT
        doc = SimpleDocTemplate(
            summary_temp.name,
            pagesize=A4
        )

        styles = getSampleStyleSheet()

        elements = []

        # ===== TITLE =====
        elements.append(
            Paragraph(
                '<b>Applicant Screening Summary</b>',
                styles['Title']
            )
        )

        elements.append(Spacer(1, 25))

        # ===== IDENTITY TITLE =====
        elements.append(
            Paragraph(
                '<b>Identity</b>',
                styles['Heading2']
            )
        )

        elements.append(Spacer(1, 10))

        # ===== APPLICANT INFO TABLE =====
        applicant_data = [

            ['Name', applicant.name],

            ['Email', applicant.email],

            ['Phone', applicant.phone or '-'],

            ['Birth Date', str(applicant.birth_date or '-')],

            ['Age', f'{applicant.age} Years' if applicant.age else '-'],

            ['Education', applicant.education or '-'],

            ['School / University', applicant.school_name or '-'],

            ['Major', applicant.major or '-'],
        ]

        # Tambahkan pengalaman kerja kalau ada
        if applicant.has_experience == 'yes':

            applicant_data.extend([

                [
                    'Last Company',
                    applicant.company_name or '-'
                ],

                [
                    'Last Position',
                    applicant.position or '-'
                ],

                [
                    'Work Start',
                    str(applicant.work_start or '-')
                ]

            ])

            # Kalau masih bekerja
            if applicant.still_working == 'yes':

                applicant_data.extend([

                    [
                        'Employment Status',
                        'Still Working'
                    ]

                ])

            else:

                applicant_data.extend([

                    [
                        'Work End',
                        str(applicant.work_end or '-')
                    ],

                    [
                        'Work Duration',
                        applicant.work_duration or '-'
                    ]

                ])

        applicant_table = Table(
            applicant_data,
            colWidths=[180, 270]
        )

        applicant_table.setStyle(TableStyle([

            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),

            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),

            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),

            ('GRID', (0, 0), (-1, -1), 1, colors.black),

            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),

            ('TOPPADDING', (0, 0), (-1, -1), 8),

        ]))

        elements.append(applicant_table)

        elements.append(Spacer(1, 25))

        # ===== SCREENING RESULT TITLE =====
        elements.append(
            Paragraph(
                '<b>Screening Result</b>',
                styles['Heading2']
            )
        )

        elements.append(Spacer(1, 10))

        # ===== SCREENING RESULT TABLE =====
        if screening_result:

            # Format decision text
            decision_text = (
                screening_result.final_decision
                .replace('_', ' ')
                .title()
            )

            # Decision color
            if screening_result.final_decision == 'recommended':
                decision_color = 'green'

            else:
                decision_color = 'red'

            screening_data = [
                [
                    'Position Applied',
                    applicant.job.title if applicant.job else '-'
                ],

                [
                    'Similarity Score',
                    f'{screening_result.similarity_score:.3f}'
                ],

                [
                    'Decision',

                    Paragraph(
                        f'<font color="{decision_color}"><b>{decision_text}</b></font>',
                        styles['BodyText']
                    )
                ]
            ]

        else:

            screening_data = [
                ['Similarity Score', '-'],
                ['Decision', 'Not Processed']
            ]

        screening_table = Table(
            screening_data,
            colWidths=[150, 300]
        )

        screening_table.setStyle(TableStyle([

            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),

            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),

            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),

            ('GRID', (0, 0), (-1, -1), 1, colors.black),

            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),

            ('TOPPADDING', (0, 0), (-1, -1), 8),

        ]))

        elements.append(screening_table)

        elements.append(Spacer(1, 25))

        # ===== BUILD SUMMARY PDF =====
        doc.build(elements)

        # ===== MERGE PDF =====
        merger = PdfMerger()

        merger.append(summary_temp.name)

        # Append original CV
        if (
            applicant.cv_file_path
            and os.path.exists(applicant.cv_file_path)
        ):
            merger.append(applicant.cv_file_path)

        merger.write(merged_temp.name)

        merger.close()

        # ===== RETURN PDF =====
        return send_file(
            merged_temp.name,
            as_attachment=False,
            mimetype='application/pdf',
            download_name=f'{applicant.name}_summary.pdf'
        )   

    # ===== CHANGE PASSWORD =====
    @app.route('/admin/admin_account', methods=['GET', 'POST'])
    @login_required
    @no_cache
    def admin_account():
        """Admin account management - change password"""
        if request.method == 'POST':
            username = request.form.get('username')
            new_password = request.form.get('new_password')
            
            # Validasi input
            if not all([username, new_password]):
                flash('Harap isi semua field!', 'danger')
                return redirect(request.url)
            
            if len(new_password) < 6:
                flash('Password minimal 6 karakter!', 'danger')
                return redirect(request.url)
            
            try:
                # Langsung update current_user (objek UserMixin dari Flask-Login)
                current_user.username = username
                current_user.password = new_password
                
                db.session.commit()
                
                flash('Username dan password berhasil diubah!', 'success')
                return redirect(url_for('admin_dashboard'))
                
            except Exception as e:
                flash(f'Gagal update: {str(e)}', 'danger')
                db.session.rollback()
                return redirect(request.url)
    
        return render_template('admin/admin_account.html')

    
    # ===== EXPORT ROUTES =====
    @app.route('/admin/export/applicants/csv')
    @login_required
    @no_cache
    def export_applicants_csv():
        applicants = Applicant.query.all()
        
        data = []
        for applicant in applicants:
            screening = ScreeningResult.query.filter_by(
                applicant_id=applicant.id
            ).first()
            
            data.append({
                'ID': applicant.id,
                'Nama': applicant.name,
                'Email': applicant.email,
                'Telepon': applicant.phone or '-',
                'Usia': applicant.age,
                'Pendidikan': applicant.education,
                'Universitas': applicant.school_name,
                'Jurusan': applicant.major,
                'Pengalaman Kerja': applicant.company_name,
                'Posisi Terakhir': applicant.position,
                'Lowongan': applicant.job.title if applicant.job else 'N/A',
                'Tanggal Apply': applicant.applied_at.strftime('%Y-%m-%d %H:%M'),
                'Similarity Score MPNet': screening.similarity_score if screening else 'N/A',
                'Keputusan Akhir': screening.final_decision if screening else 'N/A'
            })
        
        df = pd.DataFrame(data)
        
        output = io.StringIO()
        df.to_csv(output, index=False, encoding='utf-8')
        output.seek(0)
        
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'pelamar_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        )
    
    @app.route('/admin/export/applicants/excel')
    @login_required
    @no_cache
    def export_applicants_excel():
        applicants = Applicant.query.all()
        
        data = []
        for applicant in applicants:
            screening = ScreeningResult.query.filter_by(
                applicant_id=applicant.id
            ).first()
            
            data.append({
                'ID': applicant.id,
                'Nama': applicant.name,
                'Email': applicant.email,
                'Telepon': applicant.phone or '-',
                'Usia': applicant.age,
                'Pendidikan': applicant.education,
                'Universitas': applicant.school_name,
                'Jurusan': applicant.major,
                'Pengalaman Kerja': applicant.company_name,
                'Posisi Terakhir': applicant.position,
                'Lowongan': applicant.job.title if applicant.job else 'N/A',
                'Tanggal Apply': applicant.applied_at.strftime('%Y-%m-%d %H:%M'),
                'Similarity Score (MiniLM)': screening.similarity_score if screening else 'N/A',
                'Keputusan Akhir': screening.final_decision if screening else 'N/A'
            })

        df = pd.DataFrame(data)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Pelamar')
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'pelamar_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )
    
    # ===== INITIAL SETUP =====
    with app.app_context():
        try:
            # Cek koneksi
            db.session.execute(text('SELECT 1'))
            print("✅ MySQL Connection successful!")
            
            # Create tables
            db.create_all()
            print("✅ Tables created!")
            
            # Check data
            admin_count = Admin.query.count()
            job_count = Job.query.count()
            applicant_count = Applicant.query.count()
            
            print(f"📊 Database Status:")
            print(f"   - Admins: {admin_count}")
            print(f"   - Jobs: {job_count}") 
            print(f"   - Applicants: {applicant_count}")
            
            # Sample data
            # if job_count == 0:
            #     sample_jobs = [
            #         Job(title='Software Engineer', description='Develop web applications', requirements='Python, Flask, MySQL', is_active=True),
            #         Job(title='Data Scientist', description='Build ML models', requirements='Python, scikit-learn, SQL', is_active=True),
            #     ]
            #     db.session.add_all(sample_jobs)
            #     db.session.commit()
            #     print("✅ Sample jobs created")
            
            # if admin_count == 0:
            #     print("⚠️  No admin found. Will auto-create on first login.")

            # Sample data
            if job_count == 0:
                sample_jobs = [
                    Job(
                        title='Software Engineer',
                        description='Develop web applications',
                        responsibilities='Develop, maintain, test, and improve web applications using Python Flask and MySQL.',
                        requirements='Python, Flask, MySQL',
                        is_active=True
                    ),
                    Job(
                        title='Data Scientist',
                        description='Build ML models',
                        responsibilities='Collect, process, analyze data, build machine learning models, and evaluate model performance.',
                        requirements='Python, scikit-learn, SQL',
                        is_active=True
                    ),
                ]
                db.session.add_all(sample_jobs)
                db.session.commit()
                print("✅ Sample jobs created")

            if admin_count == 0:
                print("⚠️  No admin found. Will auto-create on first login.")
                
        except Exception as e:
            print(f"❌ Database error: {e}")
    
    return app

if __name__ == '__main__':
    app = create_app()
    
    # Create directories
    os.makedirs('uploads/cv', exist_ok=True)
    
    print("\n" + "="*60)
    print("🎓 SKRIPSI - CV SCREENING SYSTEM")
    print("="*60)
    print("📍 Public Site: http://localhost:5000")
    print("📍 Admin: http://localhost:5000/admin/login")
    print("👤 Login: admin / password")
    print("🎯 Methods: MPNet + Cosine")
    print("="*60)
    print("🚀 Starting app...")
    
    app.run(host='0.0.0.0', port=5000)