#!/usr/bin/env python3
"""
Generate Robinhood OAuth Token Locally
Authenticates with Robinhood and retrieves OAuth token for MCP integration
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime
import getpass

print("\n" + "="*100)
print("ROBINHOOD OAUTH TOKEN GENERATOR")
print("="*100)

# ============================================================================
# OPTION 1: Robinhood Web OAuth (Recommended)
# ============================================================================

def option_web_oauth():
    """Get token via Robinhood web OAuth"""
    print("\n[OPTION 1] Robinhood Web OAuth (Recommended)")
    print("-" * 100)
    print("""
To get your OAuth token from Robinhood web:

1. Go to: https://robinhood.com/settings
2. Click: Account → Connected Applications
3. Look for: "Claude Trading Bot" or similar app
4. If not listed:
   - Click: "Connect New App"
   - Select: Claude/Anthropic integration
   - Grant permissions
5. Copy the Authorization Token
6. Paste below when prompted

Note: Token typically starts with "Bearer " or similar
""")

    token = input("\nEnter your Robinhood OAuth token: ").strip()

    if not token:
        print("❌ No token provided")
        return None

    return token


# ============================================================================
# OPTION 2: Manual Robinhood API Auth
# ============================================================================

def option_api_auth():
    """Authenticate via Robinhood API directly"""
    print("\n[OPTION 2] Robinhood API Direct Auth")
    print("-" * 100)

    try:
        import requests
    except ImportError:
        print("❌ 'requests' library not found. Install with: pip install requests")
        return None

    print("Enter your Robinhood login credentials:")
    username = input("Robinhood username/email: ").strip()
    password = getpass.getpass("Password (hidden): ")

    if not username or not password:
        print("❌ Username or password empty")
        return None

    try:
        print("\n[*] Authenticating with Robinhood API...")

        # Robinhood API endpoint
        auth_url = "https://api.robinhood.com/oauth2/token/"

        auth_data = {
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": "c82SH0WZOsXWOEJw",  # Robinhood public client ID
            "expires_in": 86400
        }

        response = requests.post(auth_url, data=auth_data, timeout=10)

        if response.status_code == 200:
            token_data = response.json()
            token = token_data.get("access_token")

            if token:
                print(f"✅ Authentication successful!")
                print(f"Token (first 20 chars): {token[:20]}...")
                return token
            else:
                print("❌ No access_token in response")
                print(f"Response: {token_data}")
                return None
        else:
            print(f"❌ Authentication failed (Status {response.status_code})")
            print(f"Response: {response.text}")
            return None

    except Exception as e:
        print(f"❌ Error: {e}")
        return None


# ============================================================================
# OPTION 3: Paste from Existing Setup
# ============================================================================

def option_existing_setup():
    """Use token from existing setup"""
    print("\n[OPTION 3] Use Existing Token")
    print("-" * 100)
    print("If you already have a token from your previous setup:")

    token = input("\nPaste your existing OAuth token: ").strip()

    if not token:
        print("❌ No token provided")
        return None

    return token


# ============================================================================
# SAVE TOKEN
# ============================================================================

def save_token(token: str):
    """Save token to multiple locations"""

    if not token:
        print("❌ No token to save")
        return False

    print("\n" + "="*100)
    print("SAVING TOKEN")
    print("="*100)

    # Option 1: Environment Variable
    print("\n[1] Add to ~/.bashrc or ~/.zshrc:")
    print(f"""
export ROBINHOOD_AUTH_TOKEN="{token}"
""")

    # Option 2: .env file
    env_path = Path.home() / ".robinhood_oauth"
    try:
        with open(env_path, 'w') as f:
            f.write(f"ROBINHOOD_AUTH_TOKEN={token}\n")
        print(f"\n[2] ✅ Saved to: {env_path}")
        print(f"   Use with: source {env_path}")
    except Exception as e:
        print(f"\n[2] ❌ Could not save to {env_path}: {e}")

    # Option 3: .env in trading_bot directory
    trading_bot_env = Path.home() / "trading_bot" / ".env"
    try:
        if trading_bot_env.parent.exists():
            with open(trading_bot_env, 'a') as f:
                f.write(f"\nROBINHOOD_AUTH_TOKEN={token}\n")
            print(f"\n[3] ✅ Saved to: {trading_bot_env}")
            print(f"   Bot will auto-load this file")
    except Exception as e:
        print(f"\n[3] ❌ Could not save to {trading_bot_env}: {e}")

    # Option 4: Token info
    print("\n[4] Token Details:")
    print(f"    Type: OAuth Bearer Token")
    print(f"    Length: {len(token)} characters")
    print(f"    First 20 chars: {token[:20]}...")
    print(f"    Saved at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return True


# ============================================================================
# VERIFY TOKEN
# ============================================================================

def verify_token(token: str):
    """Verify token works"""
    print("\n" + "="*100)
    print("VERIFYING TOKEN")
    print("="*100)

    try:
        import requests
    except ImportError:
        print("⚠️  'requests' not available for verification")
        print("Install with: pip install requests")
        return True  # Can't verify but maybe it works

    try:
        print("\n[*] Testing token with Robinhood API...")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        response = requests.get(
            "https://api.robinhood.com/user/",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            user_data = response.json()
            username = user_data.get("username", "Unknown")
            print(f"✅ Token is VALID")
            print(f"   Logged in as: {username}")
            return True
        else:
            print(f"⚠️  Token verification uncertain (Status {response.status_code})")
            print(f"   Response: {response.text[:200]}")
            return False

    except Exception as e:
        print(f"⚠️  Could not verify token: {e}")
        print("   Token may still be valid - MCP will test it")
        return False


# ============================================================================
# MAIN MENU
# ============================================================================

def main():
    print("\nHow would you like to get your Robinhood OAuth token?\n")
    print("[1] From Robinhood web app (Recommended)")
    print("[2] Authenticate via Robinhood API directly")
    print("[3] Paste existing token")
    print("[4] Exit")

    choice = input("\nEnter choice (1-4): ").strip()

    token = None

    if choice == "1":
        token = option_web_oauth()
    elif choice == "2":
        token = option_api_auth()
    elif choice == "3":
        token = option_existing_setup()
    elif choice == "4":
        print("Exiting...")
        sys.exit(0)
    else:
        print("Invalid choice")
        return

    if not token:
        print("\n❌ Failed to get token")
        sys.exit(1)

    # Verify token
    verify_token(token)

    # Save token
    save_token(token)

    # Final instructions
    print("\n" + "="*100)
    print("NEXT STEPS")
    print("="*100)
    print("""
1. Set environment variable:
   export ROBINHOOD_AUTH_TOKEN="{token}"

2. Test bot with MCP:
   cd ~/trading_bot
   python3 bot_final_production_v38.py

3. Check logs:
   tail -f ~/trading_bot/bot_v38.log | grep "MCP"

4. Expected output:
   MCP Status: ENABLED ✅
   ✅ MCP ORDER: SYMBOL BUY X @ $price
""".format(token=token[:20] + "..."))

    print("="*100 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExiting...")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
