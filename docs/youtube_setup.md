# Youtube setup

## Create Google Account

## Create API

- Go to [credentials](https://console.cloud.google.com/apis/credentials)
  - Push `CREATE CREDENTIALS` -> `API key`

(youtube-data-api-v3 should be enabled)

## Create OAuth 2.0 Client

- Go to [credentials](https://console.cloud.google.com/apis/credentials)
  - Push `CREATE CREDENTIALS` -> `OAuth client ID`
- In the field `Authorized redirect URIs` add url `http://localhost:5500/`
- Download oauth client credentials (json file).
- Rename to `client_secret.json`
- Save it to `THIS_REPO/data/credentials/youtube/json_client.json`

## Add to dotenv variables

```python
YOUTUBE_STREAM_API_KEY="yourapikeygdjfgfdg"

# Get from googlecloud console api. Enable youtube Data api V3.

YOUTUBE_CHANNEL_ID="channelidnotnamegdfhfgh"

# Copy your channel ID, not name. Google if troubles.
```


