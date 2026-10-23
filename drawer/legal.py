PRIVACY = """
<h1>Privacy</h1>
<p class="small">Drawer is a hackathon prototype. This page says exactly what the code does.</p>
<h2>What we keep</h2>
<p>Names of things you bought, stores, notes, where things are, vendor names and phone numbers,
and the incidents you report are encrypted before they reach the disk. Each household has its own
encryption key, derived from a master key that never sits in the code or the repository.</p>
<p>These stay readable to whoever runs the server: purchase, return and warranty dates, the time of
each incident, and counts of entries. We need dates to sort deadlines.</p>
<h2>What we do not keep</h2>
<p>No email address, phone number or real name is asked for. Your passphrase is stored only as a salted
hash, so we cannot recover it. Sign-in tokens are stored only as hashes. Server logs do not contain
what you said.</p>
<h2>Who sees it</h2>
<p>Nobody without your passphrase. A guest code opens only the entries you marked guest-safe, and it
expires by itself. When the optional AI helper is switched on, your text goes to Amazon Bedrock after card
numbers, emails, phone numbers and street addresses are stripped out. Switched off, nothing leaves the server.</p>
<h2>Deleting</h2>
<p>Say "forget everything" or call the forget_everything tool with confirmation. It deletes every entry,
incident, guest code and token, removes the household, and compacts the database file.</p>
<h2>Contact</h2><p>Questions: <span id="contact">set DRAWER_CONTACT before you publish</span></p>
"""
TERMS = """
<h1>Terms</h1>
<p class="small">Plain terms for a prototype.</p>
<h2>Not an emergency service</h2>
<p>Drawer repeats what you saved and gives general first steps. If you smell gas, see smoke or fire, or
feel unsafe, leave and call your local emergency number. Drawer cannot call anyone for you.</p>
<h2>Check your dates</h2>
<p>Return windows and warranty dates are the ones you told Drawer. Stores change their rules, so confirm
with the receipt or the store before you rely on a date.</p>
<h2>Your data, your risk</h2>
<p>If you lose your passphrase, your data cannot be recovered. The service is provided as is, with no
promise that it will always be available.</p>
<h2>Drafts</h2><p>Claim messages are drafts. Drawer never sends anything. You read them and send them yourself.</p>
"""
