"""The photo library on Google Drive. READ ONLY, by scope and by construction.

oauth.py signs in as Chris (installed-app flow) asking for exactly
`drive.readonly`; api.py can only issue GET requests; scan.py builds the
inventory and follows the Changes API. Nothing in this package can create,
modify, move, rename, share or delete anything in Drive, and
tests/test_drive_readonly.py pins that.
"""
