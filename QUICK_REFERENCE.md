# Red Day DCA - Quick Reference Card

## Trigger Rules
| Type | Threshold | Description |
|------|-----------|-------------|
| Intraday Dip | ≤ -4.7% | Price drops 4.7%+ below yesterday's close at any point |
| Close-to-Close | ≤ -3.3% | Daily candle closes 3.3%+ below prior close |

**Limits**: Max 1 trigger/day, Max 15 triggers total

---

## Per-Trigger Crypto Order (to Caleb & Brown)

### Every Trigger (1-15):
| Asset | Amount |
|-------|--------|
| LINK | £666.67 |
| ONDO | £533.33 |
| TAO | £533.33 |
| RENDER | £533.33 |
| TRAC | £333.33 |
| **Subtotal** | **£2,600.00** |

### Every 3rd Trigger (3, 6, 9, 12, 15) - ADD:
| Asset | Amount |
|-------|--------|
| BANANA | £100.00 |
| BONK | £100.00 |
| **3rd Trigger Total** | **£2,800.00** |

---

## Per-Trigger eToro Order (Manual - you receive email)

| Stock | Amount |
|-------|--------|
| COIN | £233.33 |
| NVDA | £200.00 |
| PLTR | £166.67 |
| **Total** | **£600.00** |

---

## Total Portfolio After 15 Triggers

### Crypto (via Caleb & Brown): £40,000
| Asset | Total |
|-------|-------|
| LINK | £10,000.05 |
| ONDO | £7,999.95 |
| TAO | £7,999.95 |
| RENDER | £7,999.95 |
| TRAC | £4,999.95 |
| BANANA | £500.00 |
| BONK | £500.00 |

### Equities (via eToro): £9,000
| Stock | Total |
|-------|-------|
| COIN | £3,499.95 |
| NVDA | £3,000.00 |
| PLTR | £2,500.05 |

### Speculative Buffer: £1,000
(Remaining from £50k total)

---

## Email Recipients

| Recipient | Email | Purpose |
|-----------|-------|---------|
| Jake (Broker) | jake@calebandbrown.com | Crypto buy orders |
| Lewis (You) | lewis@jackson.ventures | eToro action alerts |

---

## Trigger Schedule

```
Trigger 1  → Core crypto only
Trigger 2  → Core crypto only
Trigger 3  → Core crypto + BANANA + BONK ⭐
Trigger 4  → Core crypto only
Trigger 5  → Core crypto only
Trigger 6  → Core crypto + BANANA + BONK ⭐
Trigger 7  → Core crypto only
Trigger 8  → Core crypto only
Trigger 9  → Core crypto + BANANA + BONK ⭐
Trigger 10 → Core crypto only
Trigger 11 → Core crypto only
Trigger 12 → Core crypto + BANANA + BONK ⭐
Trigger 13 → Core crypto only
Trigger 14 → Core crypto only
Trigger 15 → Core crypto + BANANA + BONK ⭐ (FINAL)
```

---

## Commands

**Check logs:**
```bash
railway logs
```

**Redeploy after changes:**
```bash
railway up
```

**Stop the service:**
Railway Dashboard → Service → Settings → Delete (or pause)
