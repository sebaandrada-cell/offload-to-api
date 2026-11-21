# Security policy

## What to report

Anything that could expose a user's secrets or personal data or spend their money without them noticing. For example:
- a secret or personal identifier that the masking should catch but does not (see `plugins/offload-to-api/scripts/masking.py` and `personal.py` for what is covered);
- a way to bypass the daily spend cap or corrupt the spend ledger;
- a file written with permissions that expose sensitive data;
- a problem in `install.sh` or in the plugin's skill that could run something the user did not ask for.

Masking is pattern-based and is known to miss things. A missed format is still worth reporting: send a fake example, never a real value.

## How to report

Open an issue at https://github.com/sebaandrada-cell/offload-to-api/issues with the title "Security" and **no technical details**. Say only that you have a security report and how you prefer to be contacted. The maintainer will then arrange a private channel. If the problem is a missed masking format that uses only fake data, you can open a normal issue with the example.

Never post real keys, tokens, IBANs, ID numbers or other personal data in an issue. If you did by mistake, revoke the key first and then tell us.

## Supported versions

Only the latest release on `main` gets fixes.
