# cd main
# streamlit run main.py
import streamlit as st
import os
import time
from datetime import datetime, timedelta
import Quartz
from Foundation import NSDistributedNotificationCenter, NSObject
import pickle
import os.path
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import subprocess
from urllib.parse import urlparse
import pandas as pd

DEBUG_MODE = False  # True
class Config:
    if DEBUG_MODE:
        CHECK_INTERVAL = 1   # アプリケーションのチェック間隔（秒）30sごと
        SLEEP_DETECTION = 5  # 一時停止していたことを検知する時間
        APP_CHANGE_MIN_DURATION = 3  # アプリの変化を認識する最小期間（秒）3分
        INACTIVITY_DURATION = 10  # 非活動とみなす期間（秒）5分(300s)
        RESUME_ACTIVITY_DURATION = 3  # 休止からの復帰にかかる待機時間
        DETAILED_PRINT = True
        GOOGLE_CALENDAR = True  # False
        MIN_EVENT_DURATION = 2  # イベントの最小時間(min)
        CLIENT_SECRET_FILE = '../secret_key/client_secret_.apps.googleusercontent.com.json'
    else:
        CHECK_INTERVAL = 3  # 30
        SLEEP_DETECTION = 180
        APP_CHANGE_MIN_DURATION = 60
        INACTIVITY_DURATION = 180
        RESUME_ACTIVITY_DURATION = 60
        DETAILED_PRINT = True
        GOOGLE_CALENDAR = True  # False
        MIN_EVENT_DURATION = 15  # イベントの最小時間(min)
        CLIENT_SECRET_FILE = '../secret_key/client_secret_.apps.googleusercontent.com.json'

class Task:
    def __init__(self, app_name, start_time=None):
        self.app_name = app_name
        self.domain_list = []
        if start_time:
            self.start_time = start_time
        else:
            self.start_time = datetime.now()
        self.end_time = None
        self.event_created = False
    
    def end(self, time=None):
        if time:
            self.end_time = time
        else:
            self.end_time = datetime.now()
            
    def add_domain(self, timestamp, domain):
        self.domain_list.append((timestamp, domain))

    def __str__(self):  # インスタンスを文字列で表示するときに実行される
        duration = self.end_time - self.start_time if self.end_time else datetime.now() - self.start_time
        return f"{(datetime.min + duration).time().strftime('%H:%M:%S')}, App: {self.app_name}"
    
class AppTracker:
    def __init__(self):  # コントラクタ
        self.current_app = self.get_active_app()  # 初期値を現在のアプリに設定
        self.current_domain = None
        self.potential_new_app = None
        self.last_app_switch_time = datetime.now()
        self.active_app_for_period = None
        self.potential_switch_time = None
        self.last_activity_time = datetime.now()
        self.user_inactive = False  # ユーザーが非活動状態かどうかを示すフラグ
        self.potential_resume_time = None  # ユーザーが活動を再開してからの時間を追跡する変数
        self.current_task = None  # シーケンスが開始している間だけtaskインスタンスが入る変数
        self.task_list = []
        self.idle_seconds = None
        self.service = self.setup_google_calendar_service()
        self.start_using_app(self.get_active_app())

    def setup_google_calendar_service(self):
        SCOPES = ['https://www.googleapis.com/auth/calendar']

        creds = None
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(Config.CLIENT_SECRET_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
                with open('token.pickle', 'wb') as token:
                    pickle.dump(creds, token)

        return build('calendar', 'v3', credentials=creds)

    def add_event_to_google_calendar(self, summary, start_time, end_time):
        """Add event to Google Calendar"""

        # self.current_task.domain_list を文字列形式に変換
        domain_list_str = ""
        if self.current_task and self.current_task.domain_list:
            for timestamp, domain in self.current_task.domain_list:
                domain_list_str += f"{timestamp.strftime('%Y-%m-%d %H:%M:%S')}, {domain}\n"   

        event = {
            'summary': summary,
            'description': domain_list_str,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'Asia/Tokyo',
            },
        }
        event = self.service.events().insert(calendarId='primary', body=event).execute()
        st.success(f'Event created: {event.get("htmlLink")}')

    def get_active_app(self):
        """Get the name of the currently active application."""
        try:
            active_app = os.popen('osascript -e \'tell application "System Events" to get name of first application process whose frontmost is true\'').read().strip()
            return active_app
        except Exception as e:
            st.error(f"Error getting active app: {e}")
            return None

    def get_sidekick_domain(self):
        applescript_cmd = """
        tell application "Sidekick"
            get URL of active tab of front window
        end tell
        """
        result = subprocess.run(['osascript', '-e', applescript_cmd], capture_output=True, text=True)

        # URLからドメインを抽出
        parsed_url = urlparse(result.stdout.strip())
        return parsed_url.netloc  # netloc属性にはドメイン名が含まれています
        
    def start_using_app(self, app_name, time=None):
        """アプリの使用を開始したときの処理"""
        self.current_task = Task(app_name, time)
        self.task_list.append(self.current_task)
        self.current_app = app_name
        if app_name == 'Sidekick':
            self.current_domain = self.get_sidekick_domain()
            self.current_task.add_domain(self.current_task.start_time, self.current_domain)
        else:
            self.current_domain = ''
        # st.info(f"Start : {app_name}, {self.current_domain}, {self.current_task.start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    def end_using_app(self, app_name, time=None):
        """アプリの使用を終了したときの処理"""
        # st.info(f"End : {app_name}, {time.strftime('%Y-%m-%d %H:%M:%S')}")
        if self.current_task:
            self.current_task.end(time)

            # st.info(f"{self.current_task}[Task report]\n")  # タスクの情報を表示（必要に応じてファイルに保存なども考えられる）
            duration = self.current_task.end_time - self.current_task.start_time
            if Config.GOOGLE_CALENDAR and duration >= timedelta(minutes=Config.MIN_EVENT_DURATION):
                self.add_event_to_google_calendar(f"App:{self.current_task.app_name}",
                                                    self.current_task.start_time,
                                                    self.current_task.end_time)
                self.current_task.event_created = True
            self.current_task = None
        
    def get_user_activity_time(self):
        """ユーザーの最後のアクティビティからの経過時間[s]"""
        idle_seconds = Quartz.CGEventSourceSecondsSinceLastEventType(Quartz.kCGEventSourceStateHIDSystemState, Quartz.kCGAnyInputEventType)
        return idle_seconds
    def create_task_df(self, task_list):
        """タスクリストから DataFrame を作成"""
        data = []
        for task in task_list:
            data.append({
                "App Name": task.app_name,
                "Domain Name": None,
                "Duration": (lambda es: f"{es // 60} m {es % 60} s" if es >= 60 else f"{es} s")(int(((task.end_time if task.end_time else datetime.now()) - task.start_time).total_seconds())),
                "Domain Name": ', '.join([domain for timestamp, domain in task.domain_list]),
                "Start Time": task.start_time.strftime('%Y-%m-%d %H:%M:%S'),
                "End Time": task.end_time.strftime('%Y-%m-%d %H:%M:%S') if task.end_time else None,
                "Event created" : task.event_created
            })
        return pd.DataFrame(data)    

def main():
    st.set_page_config(page_title="Lifelog on macOS", page_icon="None", layout="wide", initial_sidebar_state="auto", menu_items=None)
    st.title("Lifelog on macOS")
    tab1, tab2 = st.tabs(["Current", "Settings"])

    with tab1:
        tab1_current_using = st.empty()
        tab1_current_idol = st.empty()
        tab1_table = st.empty()
        tab1_current_using_potential = st.empty()

        tab1_infomation_placeholder = st.empty()
        tracker = AppTracker()  # インスタンス生成
    
    with tab2:
        if st.button('Googleの認証が使えない時はここを押して認証情報をリセット'):
            time.sleep(1)

    try:
        while True:
            app = tracker.get_active_app()              
            tracker.idle_seconds = tracker.get_user_activity_time()
            user_currently_inactive = tracker.idle_seconds >= Config.INACTIVITY_DURATION  # ユーザーが設定分以上、非活動かどうかをチェック

            if tracker.current_task is not None and tracker.current_task.start_time is not None: display_time = (lambda es: f"{es // 60} m {es % 60} s" if es >= 60 else f"{es} s")(int((datetime.now() - tracker.current_task.start_time).total_seconds()))
            if tracker.current_task is not None: tab1_current_using.markdown(f"<div style='color: blue; font-size: 30px;'>● {tracker.current_task.app_name}  ({tracker.current_domain}){display_time}</div>", unsafe_allow_html=True)  # blue, green, red
            if tracker.potential_new_app is not None and tracker.current_task.app_name != app: 
                tab1_current_using_potential.text(f'Currentry using {tracker.potential_new_app} for {(int((datetime.now() - tracker.potential_switch_time).total_seconds()))}s. (It will be the task if you use {Config.APP_CHANGE_MIN_DURATION}s.)')
            else:
                tab1_current_using_potential.text('')

            # アプリが変わった場合の処理
            if app != tracker.current_app and app != tracker.potential_new_app and not tracker.user_inactive:
                tracker.potential_new_app = app
                tracker.potential_switch_time = datetime.now()

            # Start後にappが Sidekick の場合、ドメインを確認
            if tracker.current_app == 'Sidekick' and tracker.current_task is not None:
                current_domain = tracker.get_sidekick_domain()
                if current_domain != tracker.current_domain:
                    tracker.current_task.add_domain(datetime.now(), current_domain)
                    tracker.current_domain = current_domain
                    # tab1_infomation_placeholder.text(f"{tracker.current_task.domain_list[-1][0].strftime('%Y-%m-%d %H:%M:%S')}, {tracker.current_task.domain_list[-1][1]}")

            # potential_new_app が存在し、 設定秒以上前面にある場合、current_app として認識
            if tracker.potential_new_app and (datetime.now() - tracker.potential_switch_time).seconds >= Config.APP_CHANGE_MIN_DURATION:
                tracker.end_using_app(tracker.current_app, time=tracker.potential_switch_time)  # end_using
                tracker.last_app_switch_time = tracker.potential_switch_time
                tracker.start_using_app(tracker.potential_new_app, time=tracker.potential_switch_time)  # start_using
                tracker.potential_new_app = None
            
            # 休止検出
            # 休止に入っていない時に、設定分以上非活動であれば、休止に入る
            if not tracker.user_inactive and user_currently_inactive:
                if Config.DETAILED_PRINT: tab1_infomation_placeholder.info("Inactive detected.")
                tracker.user_inactive = True
                tracker.end_using_app(tracker.current_app, time=datetime.now()-timedelta(seconds=Config.INACTIVITY_DURATION))

            # 休止に入って、触りはじめた時、その時間を記録
            elif tracker.user_inactive and not user_currently_inactive and tracker.potential_resume_time is None:
                tracker.potential_resume_time = datetime.now()
            
            # 休止に入って触りはじめた時間が記録されており、設定分経っていたら再開する
            elif tracker.potential_resume_time and (datetime.now() - tracker.potential_resume_time).seconds >= Config.APP_CHANGE_MIN_DURATION:
                tracker.start_using_app(tracker.get_active_app(), time=tracker.potential_resume_time)
                tracker.user_inactive = False
                tracker.potential_resume_time = None
            
            # 休止に入って触りはじめた時間が記録されたが、idle_secondsが設定秒以上になった時、再度休止に入る
            elif tracker.potential_resume_time and tracker.idle_seconds >= Config.RESUME_ACTIVITY_DURATION:
                tracker.potential_resume_time = None

            time.sleep(Config.CHECK_INTERVAL)


            # Streamlit で DataFrame を表示
            task_df = tracker.create_task_df(tracker.task_list)
            tab1_table.table(task_df)


    finally:
        tab1_infomation_placeholder.error(f"AppTracker has stopped tracking.{datetime.now()}")
        if tracker.current_task:
            tracker.end_using_app(tracker.current_task.app_name, tracker.current_task.start_time)

if __name__ == "__main__":
    main()