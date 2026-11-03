# Request for Proposal: Vandelay Logistics, Fleet & Operations Data Platform

**From:** Vandelay Logistics, Group Procurement (procurement@vandelay-synthetic.example)
**To:** Vendor, BTS-Synthetic
**Issued:** 2026-06-02
**Response due:** 2026-06-23
**Award expected:** 2026-07-31

*All names and figures in this document are fictional.*

## 1. About Vandelay Logistics

Vandelay Logistics is a European freight and contract-logistics group headquartered in Rotterdam. Revenue is about €2.1B (2025). We have 11,500 employees across 14 EU countries and run 9,000 trucks with on-board telematics and 64 warehouses.

Our primary cloud is AWS (eu-central-1 and eu-west-1). Analytics today runs on an Oracle Exadata warehouse and SAP BW, both of which we intend to retire.

## 2. Scope

We want a single data platform for fleet, warehouse and commercial data.

### 2.1 Workloads
- Streaming telematics from 9,000 vehicles (position, fuel, engine faults)
- Batch ETL from SAP S/4HANA, our TMS and WMS, and about 20 other sources
- BI for about 400 users on Tableau
- Route and fuel-optimisation models built by a team of 25 data scientists

### 2.2 Scale
- About 190 TB today, growing about 8 TB per month
- Peak ingest: 60,000 events per second

### 2.3 Capabilities
- All data must stay in the EU, with no processing outside the EU/EEA
- Open table formats (Iceberg or Delta)
- Certified Tableau integration
- Row-level security by country and business unit

## 3. Commercial requirements
- **Term:** 4 years, fixed pricing, no escalators.
- **Payment:** quarterly in arrears, Net 60.
- **Termination for convenience:** 60 days' notice, no penalty.

## 4. Service requirements
- **Support:** 24/7, with a P1 (critical) incident response time of 30 minutes or less.
- **Availability:** 99.9% monthly uptime.
- **Security:** ISO 27001 and SOC 2 Type II. GDPR DPA required.

## 5. Evaluation criteria

| Criterion | Weight |
| --- | --- |
| Functional fit | 30% |
| Total cost over the term | 25% |
| Delivery plan and risk | 20% |
| Contract and exit terms | 15% |
| References and vendor stability | 10% |
