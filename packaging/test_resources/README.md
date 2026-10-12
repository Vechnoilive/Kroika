These certificate/key fixtures are public synthetic test data, not credentials.
They are used only by the explicit desktop self-test to serve a Gemini-shaped HTTPS
response on 127.0.0.1. The certificate is trusted only in the diagnostic worker via
a temporary SSL_CERT_FILE, never added to the operating system trust store.
Normal application startup does not create this server or change TLS trust.
The temporary API key and Windows Credential Manager entry are created and removed
inside the isolated test profile; no user key or real Google endpoint is used.
