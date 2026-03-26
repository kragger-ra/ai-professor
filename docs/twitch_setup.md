# Twitch chat configuring


- Register/login on twitch and get your channel id
  - Id can be found on "twitch.tv/your_channel_id" 
- Create developer [profile](https://dev.twitch.tv/console/app)
- Create [app](https://dev.twitch.tv/console/app)
  - Get client identifier
  - Get client secret
- Dotenv configure

```python
TWITCH_TARGET_CHANNEL="channelid"
TWITCH_APP_SECRET="secretcode"
TWITCH_APP_ID="appclientid"
```