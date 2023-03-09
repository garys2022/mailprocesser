from __future__ import print_function

from dotenv import load_dotenv

load_dotenv()

import os.path
import os

database_url = os.getenv('DATABASE_URL')

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
from bs4 import BeautifulSoup
from models import Label
import datetime
import re
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

from models import Job_application


# If modifying these scopes, delete the file token.json.


def main():
    """Shows basic usage of the Gmail API.
    Lists the user's Gmail labels.
    """
    READ_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify']
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', READ_SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', READ_SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        # Call the Gmail API
        service = build('gmail', 'v1', credentials=creds)

        # setup label hierarchy
        parent_label = Label(name='job_hunt_mail_processor', type_='parent')
        processed = Label(name='processed', parent=parent_label, type_='processed')
        to_be_process = Label(name='to_be_process', parent=parent_label, type_='to_process')
        error = Label(name='error', parent=parent_label, type_='error')

        # Detect whether an existing label called processed have been created , raise error if not
        # get label id for parent, processed,and to_be_process
        verify_label(service, parent_label)
        results = service.users().messages().list(userId='me',
                                                  labelIds=parent_label.to_process.id,
                                                  maxResults=500).execute()
        messages = results.get('messages', [])
        # get sql engine ready
        engine = create_engine(database_url, pool_recycle=3600)

        if not messages:
            print('No labels found.')
            return
        message_count = 0
        for message in messages:
            message_count += 1
            print(message_count)
            # clean variable for each run
            for var in ['sender','sender_name','sender_email','subject','role','href','company','mail_id','date']:
                if var in locals():
                    locals()[var] = None

            msg = service.users().messages().get(userId='me', id=message['id']).execute()

            mail_id = message['id']
            # task 1/5 - date
            # Convert internaldate to seconds
            date = datetime.datetime.fromtimestamp(int(msg['internalDate']) / 1000).date()



            # task 2/5 - date, sender
            # extract sender name and sender email information
            count = 0
            for header in msg['payload']['headers']:
                if count == 2:
                    break
                if header['name'] == 'From':
                    sender = header['value']
                    sender_name = sender.split('<')[0]
                    sender_email = re.findall(r'<(.+)>', sender)[0]
                    count += 1
                elif header['name'] == 'Subject':
                    subject = header['value']
                    count += 1

            # task 5/5 date,role,href,company,sender
            # Extract job name , href , company name from ail

            for p in msg["payload"]["parts"]:
                if p["mimeType"] == "text/html":
                    if sender_email.find('linkedin.com') != -1 & subject.find('your application was sent to') != -1:
                        data = base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8")
                        role, href, company = extract_data_Linkedin(data)

                    elif (sender_email.find('indeedapply@indeed.com') != -1) & \
                            (subject.find('Indeed Application') != -1):
                        data = base64.urlsafe_b64decode(p["body"]["data"]).decode("utf-8")
                        role, href, company = extract_data_indeed(data)

                if p["mimeType"] == "multipart/alternative":
                    if sender_email.find('@email.reed.co.uk') != -1 & subject.find(
                    "We've sent your application to the recruiter") != -1:
                        for pp in p['parts']:
                            if pp["mimeType"]== "text/html":
                                data = base64.urlsafe_b64decode(pp["body"]["data"]).decode("utf-8")
                                role,href,company = extract_data_reeds(data)

            try:
                record = Job_application(**{
                    'id': mail_id,
                    'date': date,
                    'role': role,
                    'href': href,
                    'company': company,
                    'via_name': sender_name,
                    'via_email': sender_email
                })

                with Session(engine) as session:
                    try:
                        session.add(record)
                        # Modify the message to move it to the Trash folder
                        modified = False
                        modify_request = {'addLabelIds': [parent_label.processed.id], 'removeLabelIds': msg['labelIds']}
                        service.users().messages().modify(userId='me', id=mail_id, body=modify_request).execute()
                        modified = True
                        session.commit()

                    except Exception as e:
                        print('error occur , rollback.')
                        print(e)
                        session.rollback()
                        if modified:
                            modify_request = {'addLabelIds': [parent_label.error.id],
                                              'removeLabelIds': [parent_label.processed.id]}
                            service.users().messages().modify(userId='me', id=mail_id, body=modify_request).execute()
                        else:
                            modify_request = {'addLabelIds': [parent_label.error.id],
                                              'removeLabelIds': msg['labelIds']}
                            service.users().messages().modify(userId='me', id=mail_id, body=modify_request).execute()
            except UnboundLocalError as t:
                print(f'mail process failure for mail {subject} , mail moved to error tag')
                print(t)

                if 'modified' in locals():
                    if modified:
                        modify_request = {'addLabelIds': [parent_label.error.id],
                                              'removeLabelIds': [parent_label.processed.id]}
                        service.users().messages().modify(userId='me', id=mail_id, body=modify_request).execute()
                else:
                    modify_request = {'addLabelIds': [parent_label.error.id],
                                          'removeLabelIds': msg['labelIds']}
                    service.users().messages().modify(userId='me', id=mail_id, body=modify_request).execute()



    except HttpError as error:
        # TODO(developer) - Handle errors from gmail API.
        print(f'An error occurred: {error}')


def extract_data(html: str, via_mail: str, subject: str):
    """
    extract job role , hyperlink for the job , and job poster information from html of LinkedIn
    application confirmation email.

    :param html: Html of LinkedIn application confirmation email in str format
    :param via: source of job board
    :param subject: subject of the mail
    :return:    name:str  job role name applied
                href:str LinkedIn hyperlink to the job role
                company:str  Job poster
    """
    # case for LinkedIn
    if via_mail.find('linkedin.com') != -1 & subject.find('your application was sent to') != -1:
        name, href, company = extract_data_Linkedin(html)
        return name, href, company
    # case for reed
    elif via_mail.find('@email.reed.co.uk') != -1 & subject.find("We've sent your application to the recruiter") != -1:
        name, href, company = extract_data_reeds(html)
        return name, href, company
    else :
        return None


def extract_data_Linkedin(html: str):
    """
    extract job role , hyperlink for the job , and job poster information from html of LinkedIn
    application confirmation email.

    :param html: Html of LinkedIn application confirmation email in str format
    :return:    name:str  job role name applied
                href:str LinkedIn hyperlink to the job role
                company:str  Job poster
    """
    soup = BeautifulSoup(html, 'html.parser')

    a_tags = soup.find_all('a')

    name = a_tags[4].text
    href = a_tags[4].attrs['href']

    tags_with_alt = soup.find_all(attrs={'alt': True})

    company = tags_with_alt[2].attrs['alt']

    return name, href, company

def extract_data_reeds(html:str):
    soup = BeautifulSoup(html, 'html.parser')
    a_tags = soup.find_all('a')

    name = a_tags[1].text
    href = a_tags[1].attrs['href']

    count_a = 0
    td_tags = soup.find_all('td')
    for td_tag in td_tags:
        if td_tag.find('td') is None:
            count_a += 1
            if count_a == 6:
                company = td_tag.text

    return name,href,company

def extract_data_indeed(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    a_tags = soup.find_all('a')

    name = a_tags[1].text.strip()
    href = a_tags[1].attrs['href']
    company = a_tags[2].text

    return name, href, company

def verify_label(service, parent_label):
    """
    Detect whether an existing label called processed have been created ,
    Raise exception if not

    :param service: service object for Google Mail API
    :param parent_label:  parent label class with child - "to_process" and "processed" shall be created before check
    :return: None
    """

    label_message = service.users().labels().list(userId='me').execute()
    check = 0

    for current_label in label_message['labels']:
        for label in [parent_label, parent_label.error, parent_label.to_process, parent_label.processed]:
            if current_label['name'] == label.name:
                label.id = current_label['id']
                check += 1

    if check != 4:
        raise Exception(f'label check fail, please create labels '
                        f'{parent_label.name} ,'
                        f'{parent_label.error.name} ,'
                        f'{parent_label.to_process.name} '
                        f'and {parent_label.processed.name} in your gmail')
    else:
        return None


if __name__ == '__main__':
    main()
