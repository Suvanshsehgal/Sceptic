# Deploying Sceptic on one Azure VM

Everything runs on a single Ubuntu VM with Docker Compose: the web portal (installable PWA), the backend, the worker, PostgreSQL, Redis, Prometheus and Grafana. Caddy serves the site over HTTPS. The Blind-Tester sandbox works because the worker uses the VM's own Docker engine.

You do the Azure sign-in and the portal clicks yourself, because they need your student identity. Everything else is scripted.

Azure's portal changes its layout from time to time. If a label below does not match exactly, look for the closest one.

---

## Part 1. Get your Azure for Students subscription

1. Open <https://azure.microsoft.com/free/students> and choose **Activate now**.
2. Sign in with your **college email address** (the Microsoft account tied to your university). If your college has no Microsoft sign-in, create a Microsoft account first.
3. Complete the student verification when asked. It usually sends a code to your college email. No credit card is normally needed for this offer.
4. Open <https://portal.azure.com>. In the search bar type **Subscriptions** and open it. You should see **Azure for Students** with a credit balance.

**Cost control:** a VM bills while it is running. When you are not demoing, open the VM and choose **Stop** (deallocate), or turn on **Auto-shutdown** in the VM's menu.

## Part 2. Create the virtual machine

1. In the portal search bar type **Virtual machines**, then **Create → Azure virtual machine**.
2. **Basics:**
   - Subscription: Azure for Students. Resource group: **Create new**, name `sceptic-rg`.
   - Virtual machine name: `sceptic-vm`.
   - Region: pick one near you (for example Central India). Student subscriptions can restrict regions and sizes. If a size or region is refused, try another region.
   - Image: **Ubuntu Server 24.04 LTS** (x64).
   - Size: **2 vCPU and at least 4 GB of memory** (for example `Standard_B2s`, or `Standard_B2ms` for 8 GB). The worker, Prometheus and the sandbox all run here, so do not go smaller.
   - Authentication type: **SSH public key**. Username: `azureuser`. Key source: **Generate new key pair**, or paste your own. If Azure generates one, **download the `.pem` file** when prompted and keep it safe.
   - Public inbound ports: **Allow selected ports → SSH (22)**.
3. **Disks:** OS disk of 64 GB or more. Standard SSD is fine.
4. **Networking:** leave the defaults. Under **Public IP**, choose **Create new**, set **Assignment: Static**.
5. Choose **Review + create**, then **Create**. When it finishes, choose **Go to resource** and note the **Public IP address**.

### Give it a free name (needed for HTTPS)
6. In the VM's **Overview**, click the **Public IP address**, then **Configuration**.
7. Set **DNS name label** to something unique, for example `sceptic-yourname`, and **Save**.
8. Your site name is now `sceptic-yourname.<region>.cloudapp.azure.com`. Write down the exact full name; it goes in `.env` later.

### Open the web ports
9. In the VM, open **Networking** (or **Network settings**) → **Add inbound port rule**:
   - Port **80**, protocol TCP, name `allow-http`.
   - Port **443**, protocol TCP, name `allow-https`.
10. Edit the existing SSH rule (port 22) and set its **Source** to **My IP address**, so only you can log in.

## Part 3. Connect to the VM

On your Windows PC open PowerShell. Replace the path and address:

```powershell
icacls "C:\path\to\sceptic-vm_key.pem" /inheritance:r /grant:r "$($env:USERNAME):(R)"
ssh -i "C:\path\to\sceptic-vm_key.pem" azureuser@<public-ip>
```

Answer `yes` to the host-key question. You are now on the VM.

## Part 4. Put the code on the VM

**Option A, from GitHub (best):** push the project to a GitHub repository first, then on the VM:

```bash
git clone https://github.com/<you>/<repo>.git sceptic
cd sceptic
```

For a private repository, use a personal access token or a deploy key.

**Option B, copy from your PC (no GitHub):** in PowerShell on your PC, from the project folder:

```powershell
tar -czf sceptic.tgz --exclude=venv --exclude=node_modules --exclude=.git --exclude=__pycache__ --exclude="*.db" --exclude=dist .
scp -i "C:\path\to\sceptic-vm_key.pem" sceptic.tgz azureuser@<public-ip>:~
```

Then on the VM:

```bash
mkdir sceptic && tar -xzf sceptic.tgz -C sceptic && cd sceptic
```

## Part 5. Install Docker

On the VM, in the project folder:

```bash
bash deploy/azure/setup-vm.sh
```

It prints your **docker group id**. Then **log out and log back in** (`exit`, then `ssh` again) so the docker group applies, and `cd sceptic` again.

## Part 6. Configure

```bash
cp deploy/azure/.env.azure.example deploy/azure/.env
nano deploy/azure/.env
```

Fill every value:
- `SCEPTIC_DOMAIN`: your full Azure name from step 8.
- `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `GITHUB_WEBHOOK_SECRET`, `GRAFANA_ADMIN_PASSWORD`: generate each with `openssl rand -hex 32`.
- `DOCKER_GID`: the number printed by the setup script.
- `GROQ_API_KEY`: optional. Without it the platform uses deterministic checks only.

The backend **refuses to start in production** with a short or default `JWT_SECRET_KEY`, on purpose.

## Part 7. Deploy

```bash
bash deploy/azure/deploy.sh
```

The first run builds all images and takes several minutes. It also builds the sandbox image, starts everything, and creates the database tables. It ends by printing your site address.

## Part 8. See the deployed version

1. Open `https://<your-name>.<region>.cloudapp.azure.com` in a browser. The first visit takes a few seconds while Caddy obtains the certificate.
2. Click **Sign up** and create your account.
3. In Chrome or Edge, the address bar shows an **Install** icon, which installs Sceptic as an app (the PWA).

To check it from your PC without a browser:

```powershell
python deploy\azure\check_deployment.py https://<your-name>.<region>.cloudapp.azure.com
```

Grafana is private. To open it, create an SSH tunnel and browse to <http://localhost:3000>:

```powershell
ssh -i "C:\path\to\sceptic-vm_key.pem" -L 3000:localhost:3000 azureuser@<public-ip>
```

## Updating later

```bash
cd sceptic
git pull          # or copy the new files
bash deploy/azure/deploy.sh
```

## Troubleshooting

| Symptom | What to check |
|---|---|
| Browser says the site cannot be reached | The NSG rules for ports 80 and 443, and that the DNS name label matches `SCEPTIC_DOMAIN` |
| Certificate error | Port 80 must be open for the first certificate, and the name in `.env` must resolve to the VM's IP |
| `502` from `/api` | `docker compose -f deploy/azure/docker-compose.azure.yml --env-file deploy/azure/.env logs backend` |
| Backend exits at startup | `JWT_SECRET_KEY` is missing, default or shorter than 32 characters |
| Blind-Tester reports "sandbox unavailable" | `docker images` shows `sceptic-sandbox`, `DOCKER_GID` is correct, and `/var/lib/sceptic/work` exists |
| Out of disk | `docker system prune -af` removes unused images |

## Security notes

- Only ports 80 and 443 are public. The database, Redis, backend and Prometheus have no public ports. Keep SSH limited to your IP.
- The worker controls the VM's Docker engine to start sandboxes. That is powerful, so do not give untrusted people the ability to submit audits.
- Never commit `deploy/azure/.env`.
- This is a single VM with no automatic failover, which is fine for a project demonstration.
