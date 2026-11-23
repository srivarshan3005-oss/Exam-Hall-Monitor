CREATE TABLE allotments (
	id INTEGER NOT NULL, 
	student_id INTEGER NOT NULL, 
	exam_id INTEGER NOT NULL, 
	hall VARCHAR(100) NOT NULL, 
	seat VARCHAR(30) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(student_id) REFERENCES students (id), 
	FOREIGN KEY(exam_id) REFERENCES exams (id)
)
CREATE TABLE audit_logs (
	id INTEGER NOT NULL, 
	actor VARCHAR(80) NOT NULL, 
	action VARCHAR(100) NOT NULL, 
	target VARCHAR(150) NOT NULL, 
	created_at DATETIME NOT NULL, 
	details TEXT, 
	PRIMARY KEY (id)
)
CREATE TABLE exams (
	id INTEGER NOT NULL, 
	title VARCHAR(180) NOT NULL, 
	subject_code VARCHAR(30) NOT NULL, 
	exam_date VARCHAR(20) NOT NULL, 
	start_time VARCHAR(10) NOT NULL, 
	end_time VARCHAR(10) NOT NULL, 
	venue VARCHAR(150) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	PRIMARY KEY (id)
)
CREATE INDEX ix_allotments_exam_id ON allotments (exam_id)
CREATE INDEX ix_allotments_student_id ON allotments (student_id)
CREATE INDEX ix_results_exam_id ON results (exam_id)
CREATE INDEX ix_results_student_id ON results (student_id)
CREATE UNIQUE INDEX ix_students_register_number ON students (register_number)
CREATE UNIQUE INDEX ix_users_username ON users (username)
CREATE TABLE results (
	id INTEGER NOT NULL, 
	student_id INTEGER NOT NULL, 
	exam_id INTEGER NOT NULL, 
	marks FLOAT NOT NULL, 
	max_marks FLOAT NOT NULL, 
	grade VARCHAR(5) NOT NULL, 
	published BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(student_id) REFERENCES students (id), 
	FOREIGN KEY(exam_id) REFERENCES exams (id)
)
CREATE TABLE students (
	id INTEGER NOT NULL, 
	register_number VARCHAR(30) NOT NULL, 
	full_name VARCHAR(150) NOT NULL, 
	department VARCHAR(100) NOT NULL, 
	year INTEGER NOT NULL, 
	email VARCHAR(150), 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
)
CREATE TABLE users (
	id INTEGER NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	password_hash VARCHAR(300) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	student_id INTEGER, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(student_id) REFERENCES students (id)
)
