# pride CRM backend#   p r i d e _ c r m _ b a c k e n d 
 
 

[Unit]
Description=Celery Beat
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/your/project
ExecStart=/path/to/venv/bin/celery -A celery_app beat --loglevel=info
Restart=always

[Install]
WantedBy=multi-user.target


sudo systemctl enable worker.service
sudo systemctl enable beat.service
sudo systemctl start worker.service
sudo systemctl start beat.service