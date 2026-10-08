# Parali Mitra (पराली मित्र) 🌾🚜

**Parali Mitra** is an intelligent, bilingual Telegram bot designed for Indian paddy farmers in Punjab and Haryana to clear crop residue cleanly, economically, and on time—eliminating the need for stubble burning. Given a farmer's acreage, GPS location, and wheat sowing deadline, Parali Mitra computes and ranks the optimal in-situ (Happy Seeder, Super Seeder, mulcher) and ex-situ (baling & commercial sale to CBG and biomass plants) solutions based on verified net cost, logistical feasibility, weather windows via Open-Meteo, and NASA FIRMS active fire hotspots, seamlessly dispatching machine booking requests directly to custom hiring centres.

---

## Key Highlights
- **Deterministic Economics Engine:** 100% mathematical precision for rental rates, subsidies, baling logistics, and distance-based transport costs (no LLM math hallucinations).
- **Agentic Orchestration:** Powered by the open-source **Strands Agents SDK** and **Amazon Bedrock** (Claude 3.5 Sonnet) for natural, conversational Hindi/Punjabi/English dialogue and tool dispatch.
- **Serverless Architecture (AWS SAM):** API Gateway, Python 3.12 ARM64 Lambda, SQS, DynamoDB, EventBridge Scheduler, SSM Parameter Store, and CloudWatch in `ap-south-1` (Mumbai).
- **Direct Telegram Integration:** Ultra-lightweight asynchronous REST client via `httpx` tailored for serverless webhook invocation.

---

## Quickstart (Local Dev)

1. **Setup Environment:**
   ```bash
   uv venv
   .venv\Scripts\activate   # On Windows
   uv pip install -r requirements.txt
   ```

2. **Configure Secrets:**
   ```bash
   cp .env.example .env
   # Populate TELEGRAM_BOT_TOKEN, FIRMS_MAP_KEY, etc. in .env
   ```

3. **Run Unit Tests:**
   ```bash
   pytest
   ```
