import os

family = 'commons'
mylang = 'commons'
usernames['commons']['commons'] = os.getenv('PWB_USERNAME') or 'CuratorBot'

if os.getenv('PWB_CONSUMER_TOKEN') and os.getenv('PWB_CONSUMER_SECRET') and os.getenv('PWB_ACCESS_TOKEN') and os.getenv('PWB_ACCESS_SECRET'):
    authenticate['commons.wikimedia.org'] = (
        os.getenv('PWB_CONSUMER_TOKEN'),
        os.getenv('PWB_CONSUMER_SECRET'),
        os.getenv('PWB_ACCESS_TOKEN'),
        os.getenv('PWB_ACCESS_SECRET'),
    )
else:
    password_file = 'user-password.py'
