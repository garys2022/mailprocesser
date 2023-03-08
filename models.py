from sqlalchemy import Column, Integer, Date, Float, String, create_engine, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def init_db(engine):
    Base.metadata.create_all(engine, checkfirst=True)


class Job_application(Base):
    """
    SQLalchemy class object for database
    id:String  ,Gmail Email id
    date:Date ,date of email
    role:String , name of the role
    href:String , link of the role
    company:String , Hiring company/recruiter as listed
    via_name:String, job platform name
    via_email:String, job platform email
    """

    __tablename__ = "application_mail"

    id = Column('id', String(50), primary_key=True, unique=True)

    date = Column('date', Date)
    role = Column('role', Text)
    href = Column('href', Text)
    company = Column('company', Text)

    via_name = Column('via_name', Text)
    via_email = Column('via_email', Text)

    def __repr__(self):
        return f"id={self.id!r}, date={self.date!r}, role={self.role!r}, company={self.company})"


class Label:
    """
    class for gmail label used in this module
    """
    def __init__(self, name='', parent=None, type_='parent'):

        if parent is not None:
            self.parent = parent
            self.name = parent.name + '/' + name

            if type_ == 'parent':
                pass
            elif type_ == 'to_process':
                parent.to_process = self
            elif type_ == 'processed':
                parent.processed = self
            elif type_ == 'error':
                parent.error = self
            else:
                raise Exception('type should be either "parent" , "error", "to_process" or "processed only"')

        else:
            self.name = name
