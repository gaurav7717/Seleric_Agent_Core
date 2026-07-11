# MCP Database Query Capability Catalogue

## Purpose

This is the acceptance-test catalogue for a model-agnostic organizational MCP connected to Cube, ClickHouse, backend APIs, and approved action wrappers. Each query should return, where applicable:

- Result data
- Metric and dimension definitions
- Applied filters and timezone
- Data source / Cube view
- Data freshness
- Grain of the result
- Comparison method
- Provenance and query ID
- Warnings about missing, estimated, partial, or restricted data
- Supported drill-down options

A query is not considered supported merely because the MCP recognizes the words. It is supported only if the catalogue contains the required metric, dimensions, grain, join path, access policy, and deterministic execution plan.

---

# 1. System discovery and capability queries

1. What business domains can you answer questions about?
2. What metrics are available?
3. What dimensions are available?
4. What record-level entities can I retrieve?
5. What actions can I perform?
6. Which metrics support drill-down?
7. Which dimensions can be used with net revenue?
8. Which dimensions can be used with attributed orders?
9. Which metrics are available at order grain?
10. Which metrics are available at order-item grain?
11. Which metrics are available at daily, hourly, weekly, and monthly grain?
12. Which metrics are available for Meta Ads?
13. Which metrics are available for Google Ads?
14. Which metrics are available for Shopify?
15. Which metrics are available for Amazon?
16. Which metrics are available for Blinkit or other marketplaces?
17. Which metrics are available by brand?
18. Which metrics are available by country, state, and city?
19. Which metrics support campaign, ad set, and ad drill-down?
20. Which fields are restricted or considered sensitive?
21. What is the maximum date range for this metric?
22. What is the maximum row limit for record exports?
23. Which data sources are currently stale?
24. Which datasets failed their latest refresh?
25. Which metric should I use for revenue?
26. What is the difference between gross revenue, net revenue, collected revenue, and attributed revenue?
27. What is the difference between orders and attributed orders?
28. What is the difference between platform purchases and backend orders?
29. What is the difference between blended ROAS and platform ROAS?
30. Show the definition, formula, owner, source, filters, and freshness SLA for gross margin.
31. Show all synonyms for attributed orders.
32. Show all deprecated metrics and their replacements.
33. Show unsupported query combinations.
34. Why can campaign and shipping city not currently be queried together?
35. What new model or join is required to answer a specified unsupported query?

---

# 2. Time and date handling

36. Show sales today.
37. Show sales yesterday.
38. Show sales this week.
39. Show sales last week.
40. Show sales this month.
41. Show sales last month.
42. Show sales quarter to date.
43. Show sales year to date.
44. Show sales for a custom date range.
45. Show sales during the last 24 hours.
46. Show sales during the last 7, 30, 60, 90, 180, and 365 days.
47. Compare today with yesterday.
48. Compare today with the same weekday last week.
49. Compare this week with last week.
50. Compare this month with last month.
51. Compare this month with the same month last year.
52. Compare the last 7 days with the preceding 7 days.
53. Compare the last 30 days with the preceding 30 days.
54. Compare a period with the same period last year.
55. Show rolling 7-day, 14-day, 30-day, and 90-day averages.
56. Show month-to-date pace versus the previous month.
57. Forecast month-end based on current run rate.
58. Show results in IST.
59. Show results in the ad account timezone.
60. Explain which timezone was applied and why.
61. Identify incomplete current-day data.
62. Exclude today because the day is incomplete.
63. Show only completed days.
64. Show hourly performance for a specified day.
65. Show performance by day of week.
66. Show performance by hour of day.
67. Show a day-of-week by hour-of-day heatmap dataset.

---

# 3. Executive business overview

68. Give me today’s business summary.
69. Give me yesterday’s business summary.
70. Give me the last 7 days’ business summary.
71. Show revenue, orders, units, AOV, gross margin, ad spend, ROAS, and CAC.
72. Show performance versus target.
73. Show performance versus the previous period.
74. Show the biggest positive and negative changes.
75. Explain what drove revenue changes.
76. Explain what drove gross-margin changes.
77. Explain what drove ROAS changes.
78. Identify the three most important issues today.
79. Identify the three best opportunities today.
80. Show business performance by brand.
81. Show business performance by sales channel.
82. Show business performance by marketplace.
83. Show business performance by country, state, and city.
84. Show business performance by product category.
85. Show business performance by SKU.
86. Show business performance by new versus returning customers.
87. Show business performance by acquisition channel.
88. Show a CEO-ready daily summary with evidence.
89. Show a performance report with no interpretation, only verified numbers.
90. Show an exception-only report containing significant changes.

---

# 4. Revenue and order metrics

91. What is gross revenue for the selected period?
92. What is net revenue for the selected period?
93. What is total collected revenue?
94. What is refunded revenue?
95. What is cancelled revenue?
96. What is discounted revenue?
97. What is tax collected?
98. What is shipping revenue?
99. What is total order count?
100. What is valid order count?
101. What is cancelled order count?
102. What is refunded order count?
103. What is partially refunded order count?
104. What is prepaid order count?
105. What is cash-on-delivery order count?
106. What is average order value?
107. What is median order value?
108. What is average units per order?
109. What is the order conversion rate?
110. Show orders and revenue by day.
111. Show orders and revenue by week.
112. Show orders and revenue by month.
113. Show orders by hour.
114. Show net revenue by brand.
115. Show net revenue by channel.
116. Show net revenue by marketplace.
117. Show net revenue by payment method.
118. Show net revenue by country.
119. Show net revenue by state or region.
120. Show net revenue by city.
121. Show net revenue by postal code, where authorized.
122. Show net revenue by product.
123. Show net revenue by variant.
124. Show net revenue by SKU.
125. Show net revenue by collection or category.
126. Show net revenue by customer type.
127. Show net revenue by discount code.
128. Show orders using a specific discount code.
129. Show orders above or below an order-value threshold.
130. Show the top and bottom orders by value.
131. Show orders with zero or negative net revenue.
132. Show duplicate orders.
133. Show orders missing customer, location, product, or payment information.
134. Explain why order count differs between two models or reports.
135. Reconcile total order count across source, warehouse, Cube, and dashboard.

---

# 5. Order-level and order-item-level records

136. List orders for a selected period.
137. Show order ID, order name, date, status, value, customer type, city, state, and channel.
138. Find a specific order by ID or order name.
139. Show all items in a specified order.
140. Show order-item ID, order ID, SKU, product, quantity, selling price, discount, tax, cost, and margin.
141. List orders containing a specified SKU.
142. List orders containing any of several SKUs.
143. List orders containing a product category.
144. List orders from a specified city.
145. List orders from a specified campaign.
146. List orders from a specified ad, ad set, source, or medium.
147. List orders from a specified landing page or UTM value.
148. List orders from first-touch attribution.
149. List orders from last-touch attribution.
150. List orders from the selected attribution model.
151. Show which campaign generated each order.
152. Show which city each campaign-attributed order came from.
153. Show TH-383-SUSPENDER-20JUNE orders and their cities for the last 7 days.
154. Drill from campaign to orders to order items.
155. Drill from revenue by country to orders to order items.
156. Drill from SKU revenue to individual orders.
157. Drill from a daily total to records contributing to that total.
158. Show the exact records used to calculate a metric.
159. Export selected order-level records, subject to permissions.
160. Mask customer PII when the requester lacks export permission.

---

# 6. Product and SKU performance

161. Show revenue, orders, units, AOV, cost, gross profit, and margin by product.
162. Show performance by variant.
163. Show performance by SKU.
164. Show top products by revenue.
165. Show top products by units sold.
166. Show top products by gross profit.
167. Show bottom products by gross margin.
168. Show products with declining sales.
169. Show products with accelerating sales.
170. Show products with high ad spend but low revenue.
171. Show products with high page traffic but low conversion.
172. Show products with high refund rates.
173. Show products with high cancellation rates.
174. Show products with high COD return or RTO rates.
175. Show products commonly bought together.
176. Show product bundles and their attach rates.
177. Show first-product purchase versus repeat-product purchase.
178. Show new versus returning customer revenue by product.
179. Compare product performance across channels.
180. Compare product performance across regions.
181. Compare product performance before and after a price change.
182. Compare product performance before and after a campaign launch.
183. Show product contribution to total revenue and profit.
184. Show Pareto contribution: which products generate 80% of revenue?
185. Show SKU-level unit economics.
186. Show products whose selling price is below cost.
187. Show products with missing cost data.
188. Show product margin after discounts, refunds, shipping, and ad spend.
189. Identify cross-sell and upsell opportunities.
190. Identify products suitable for scaling based on demand and margin.

---

# 7. Profitability and P&L

191. Show gross profit.
192. Show gross margin percentage.
193. Show contribution margin.
194. Show contribution margin after ad spend.
195. Show net profit where all required costs are available.
196. Show cost of goods sold.
197. Show fulfilment cost.
198. Show shipping cost.
199. Show payment gateway cost.
200. Show marketplace commission.
201. Show discounts and refunds as a percentage of revenue.
202. Show P&L by day, week, and month.
203. Show P&L by brand.
204. Show P&L by channel.
205. Show P&L by product.
206. Show P&L by SKU.
207. Show P&L by country, state, and city.
208. Show P&L by campaign.
209. Show P&L by customer cohort.
210. Show net revenue and gross margin by country for the last 90 days.
211. Compare the result with the previous 90 days.
212. Explain the main changes using deterministic contribution analysis.
213. Allow drill-down to order-item level.
214. Identify where revenue increased but profit declined.
215. Identify products with positive ROAS but negative contribution margin.
216. Identify channels with high revenue but poor profitability.
217. Explain margin variance due to product mix, discounting, refunding, costs, and geography.
218. Reconcile P&L totals with financial source systems.

---

# 8. Customer analytics

219. How many unique customers purchased?
220. How many new customers purchased?
221. How many returning customers purchased?
222. What percentage of revenue came from new versus returning customers?
223. What is new-customer CAC?
224. What is returning-customer revenue?
225. What is repeat purchase rate?
226. What is customer retention by cohort?
227. What is average days to second purchase?
228. What is purchase frequency?
229. What is customer lifetime value?
230. What is LTV:CAC?
231. Show customer cohorts by first purchase month.
232. Show cohort revenue over time.
233. Show cohort repeat rates over time.
234. Show customers who purchased only once.
235. Show customers likely to repurchase based on deterministic rules.
236. Show high-value customers.
237. Show dormant customers.
238. Show customers by city, state, and country.
239. Show customer acquisition by campaign.
240. Show first-order product by cohort.
241. Show next-product purchase paths.
242. Show refund and cancellation rates by customer cohort.
243. Show COD versus prepaid behavior by cohort.
244. Show customer-level records only where authorization permits.
245. Provide aggregate customer insight when PII access is denied.

---

# 9. Marketing attribution

246. Show attributed revenue.
247. Show attributed orders.
248. Show attributed units.
249. Show attributed AOV.
250. Show attributed revenue by platform.
251. Show attributed revenue by channel.
252. Show attributed revenue by campaign.
253. Show attributed revenue by ad set.
254. Show attributed revenue by ad.
255. Show attributed revenue by source, medium, and campaign UTM.
256. Show attributed orders by campaign and city.
257. Show unattributed orders and revenue.
258. Show the attribution coverage rate.
259. Show the percentage of orders with missing campaign IDs.
260. Show first-touch attribution.
261. Show last-touch attribution.
262. Show platform-reported attribution.
263. Compare platform purchases with backend-attributed orders.
264. Explain discrepancies between Meta purchases and Shopify orders.
265. Explain discrepancies between campaign revenue and business revenue.
266. Show attribution by lookback window.
267. Show attribution by attribution model.
268. Show campaign-to-order matching confidence where applicable.
269. Show orders that match multiple campaigns.
270. Show orders with conflicting attribution fields.
271. Show orders whose UTM campaign cannot be mapped to ad metadata.
272. Show campaign name history for renamed campaign IDs.
273. Show current and historical campaign names without double-counting.
274. Reconcile attributed order totals to the canonical order model.

---

# 10. Meta Ads performance

275. Show today’s Meta Ads spend.
276. Show spend by account.
277. Show spend by campaign.
278. Show spend by ad set.
279. Show spend by ad.
280. Show impressions, reach, frequency, clicks, link clicks, CTR, CPC, CPM, purchases, CPA, purchase value, and ROAS.
281. Show outbound clicks and landing-page views where available.
282. Show video views and completion metrics.
283. Show hook rate, hold rate, thumb-stop rate, and video retention where defined.
284. Show performance by objective.
285. Show performance by placement.
286. Show performance by device.
287. Show performance by age and gender, where authorized and available.
288. Show performance by country, region, or DMA, where available.
289. Compare today versus yesterday.
290. Compare the last 7 days with the previous 7 days.
291. Compare campaign performance before and after a budget change.
292. Compare performance before and after a creative change.
293. Show campaign age and lifecycle stage.
294. Show campaigns in learning, stable, saturation, or high-risk stages.
295. Show campaigns spending without purchases.
296. Show campaigns with high CTR but low ROAS.
297. Show campaigns with low CTR but high conversion rate.
298. Show campaigns with rising frequency and falling CTR.
299. Show campaigns with rising CPA.
300. Show campaigns where platform ROAS and backend ROAS differ materially.
301. Show ads with creative fatigue signals.
302. Show the best-performing creatives.
303. Show the worst-performing creatives.
304. Show ad changes from the activity log.
305. Who changed this budget, bid, campaign, ad set, or ad, and when?
306. Explain the likely cause of a performance change using verified change events.
307. Show account-level pacing against daily or monthly budget.
308. Show underspending and overspending campaigns.
309. Show hourly spend and performance.
310. Show prime and weak time slots.
311. Show the recommended next action, clearly separated from verified facts.

---

# 11. Google Ads performance

312. Show Google Ads spend by account and campaign.
313. Show spend by campaign, ad group, ad, keyword, search term, and product item.
314. Show impressions, clicks, CTR, CPC, conversions, conversion value, CPA, and ROAS.
315. Show Shopping performance by item ID, title, brand, category, and campaign.
316. Show Performance Max asset-group performance where available.
317. Show search terms driving conversions.
318. Show search terms spending without conversions.
319. Show branded versus non-branded performance.
320. Show match-type performance.
321. Show campaign budget pacing.
322. Compare Google-reported conversions with backend orders.
323. Show products with Google spend but no backend revenue.
324. Show product-level profitability after Google spend.
325. Explain why hourly product reporting is unavailable when the API does not support it.
326. Return daily data instead of fabricating unsupported hourly data.

---

# 12. Cross-channel marketing

327. Show total marketing spend across platforms.
328. Show spend, orders, revenue, CPA, and ROAS by platform.
329. Show blended CAC.
330. Show blended ROAS.
331. Show MER or marketing efficiency ratio.
332. Show platform share of spend and revenue.
333. Compare Meta versus Google performance.
334. Compare paid versus organic revenue.
335. Compare attributed versus unattributed revenue.
336. Compare channel performance by product.
337. Compare channel performance by city or region.
338. Show duplicate attribution across platforms.
339. Show total backend orders versus total platform purchases.
340. Show cross-channel budget pacing.
341. Identify which channel drove the incremental change.
342. Recommend budget reallocation using explicit, approved rules.
343. Preview the impact of a proposed budget reallocation without executing it.

---

# 13. Funnel and conversion analytics

344. Show sessions, product views, add-to-carts, checkouts, purchases, and conversion rate.
345. Show funnel conversion by channel.
346. Show funnel conversion by campaign.
347. Show funnel conversion by landing page.
348. Show funnel conversion by device.
349. Show funnel conversion by city or region.
350. Show funnel conversion by product.
351. Identify the largest funnel drop-off.
352. Compare funnel performance with the previous period.
353. Show paid-click to session discrepancy.
354. Show session to purchase lag.
355. Show checkout abandonment rate.
356. Show cart abandonment rate.
357. Show products with strong traffic but weak checkout completion.
358. Show landing pages with high bounce or low conversion.
359. Explain whether a conversion change is due to traffic, CTR, site conversion, AOV, or attribution.

---

# 14. Inventory and supply queries

360. Show current inventory by SKU and location.
361. Show available, committed, incoming, and unavailable inventory.
362. Show low-stock SKUs.
363. Show out-of-stock SKUs.
364. Show inventory days of cover.
365. Show sell-through rate.
366. Show stock ageing.
367. Show dead stock.
368. Show fast-moving and slow-moving products.
369. Forecast stockout date using approved deterministic logic.
370. Show products at risk of stockout because of campaign scaling.
371. Show inventory value at cost.
372. Show inventory discrepancies between systems.
373. Show products sold despite zero recorded inventory.
374. Show products with sales but missing inventory mapping.
375. Show purchase-order status, where integrated.
376. Show replenishment recommendations using approved rules.
377. Preview a replenishment action.

---

# 15. Fulfilment, shipping, delivery, and returns

378. Show fulfilled, unfulfilled, partially fulfilled, shipped, delivered, cancelled, and returned orders.
379. Show fulfilment rate.
380. Show average fulfilment time.
381. Show average delivery time.
382. Show delivery SLA compliance.
383. Show shipping performance by carrier.
384. Show shipping performance by city and region.
385. Show delayed shipments.
386. Show stuck shipments.
387. Show orders without tracking numbers.
388. Show RTO orders.
389. Show RTO rate by city, state, courier, product, payment method, and campaign.
390. Show NDR orders.
391. Show NDR resolution rate.
392. Show COD confirmation performance.
393. Show return reasons.
394. Show refund reasons.
395. Show return and refund rate by product.
396. Show logistics cost per order.
397. Show shipping exceptions requiring action.
398. Retrieve an order’s current tracking status.
399. Generate or retrieve an AWB through an approved backend action.
400. Preview shipment cancellation or status update before execution.

---

# 16. Marketplace queries

401. Show sales by marketplace.
402. Show orders by marketplace.
403. Show fees and commissions by marketplace.
404. Show profit by marketplace.
405. Show product performance by marketplace.
406. Compare D2C and marketplace performance.
407. Show marketplace settlement reconciliation.
408. Show marketplace returns and cancellations.
409. Show marketplace inventory.
410. Show marketplace ad spend and attributed sales where available.
411. Show Amazon SP, SB, SD, and DSP performance where integrated.
412. Clearly state when a marketplace API or metric is not yet integrated.

---

# 17. Discounts, promotions, and pricing

413. Show discount amount and discount rate.
414. Show sales by discount code.
415. Show orders using each discount code.
416. Show gross margin after discount by code.
417. Show promotion uplift versus a comparable baseline.
418. Show coupon abuse or unusual repeated use.
419. Show orders with multiple discounts.
420. Show products most affected by discounting.
421. Show full-price versus discounted sales.
422. Show price changes by product and date.
423. Compare performance before and after price changes.
424. Show orders below the minimum profitable price.
425. Simulate the effect of a price or discount change using an approved model.

---

# 18. Finance and payment queries

426. Show sales by payment method.
427. Show prepaid versus COD mix.
428. Show payment success and failure rates.
429. Show payment gateway fees.
430. Show refunds issued and pending.
431. Show refund turnaround time.
432. Show settlements received and pending.
433. Reconcile gateway settlements with orders.
434. Reconcile marketplace settlements with orders.
435. Show taxes by jurisdiction.
436. Show invoices missing required fields.
437. Show orders requiring IRN or e-way bill based on configured rules.
438. Explain which compliance rules were applied.
439. Show finance records only according to role permissions.

---

# 19. Data quality and reconciliation

440. When was this dataset last refreshed?
441. Is today’s data complete?
442. Which pipelines are delayed?
443. Which source tables are stale?
444. Which Cube pre-aggregations are stale or failing?
445. Show row-count changes by table.
446. Show duplicate primary keys.
447. Show null rates for critical fields.
448. Show invalid date, currency, or ID values.
449. Show orphaned order items.
450. Show orphaned attribution records.
451. Show orders without products.
452. Show attribution records without orders.
453. Show ad records without metadata mappings.
454. Show products without SKU mappings.
455. Show metrics that failed validation tests.
456. Compare source totals with warehouse totals.
457. Compare warehouse totals with Cube totals.
458. Compare Cube totals with dashboard totals.
459. Explain a discrepancy with a reconciliation waterfall.
460. Show the exact SQL/API request used for a result, subject to policy.
461. Show query latency and cache status.
462. Show whether the result came from cache or live data.
463. Show whether any values were estimated or imputed.
464. Refuse to answer when required data quality checks fail.

---

# 20. Anomaly detection and diagnostic queries

465. What changed significantly today?
466. Detect unusual revenue changes.
467. Detect unusual order-volume changes.
468. Detect unusual AOV changes.
469. Detect unusual refund or cancellation changes.
470. Detect unusual spend changes.
471. Detect unusual CPA or ROAS changes.
472. Detect unusual conversion-rate changes.
473. Detect unusual product performance.
474. Detect unusual regional performance.
475. Detect unusual hourly behavior.
476. Compare an anomaly with historical baselines.
477. Quantify the anomaly’s magnitude and confidence.
478. Identify the dimensions contributing most to the anomaly.
479. Separate correlation from verified causal evidence.
480. Show relevant operational or campaign change events.
481. Explain an anomaly only from verified metrics and logged changes.
482. State when the cause cannot be determined from available data.

---

# 21. Explanation and insight-generation queries

483. Explain why revenue increased or decreased.
484. Explain why orders increased or decreased.
485. Explain why AOV changed.
486. Explain why gross margin changed.
487. Explain why ROAS changed.
488. Explain why CPA changed.
489. Explain why conversion rate changed.
490. Explain why refunds increased.
491. Explain why COD share changed.
492. Explain why a product declined.
493. Explain why a campaign declined.
494. Break a change into volume, price, mix, discount, refund, cost, and channel effects.
495. Rank drivers by absolute contribution.
496. Provide evidence links or drill-downs for every claimed driver.
497. Distinguish measured facts, derived findings, hypotheses, and recommendations.
498. Do not present a hypothesis as a verified cause.
499. Return “insufficient evidence” when appropriate.

---

# 22. Search and entity resolution

500. Find a campaign from a partial or misspelled name.
501. Find a product from its display name, SKU, alias, or historical name.
502. Find an ad from its name or ID.
503. Find an order from order number, ID, email, phone, or tracking number, subject to permissions.
504. Resolve ambiguous names to candidate entities.
505. Ask for disambiguation when multiple candidates remain.
506. Show the exact entity ID selected.
507. Match historical campaign names to stable campaign IDs.
508. Match UTM values to platform campaign metadata.
509. Match products across Shopify, ads, marketplace, and warehouse IDs.
510. Show unresolved entity mappings.

---

# 23. Query composition and multi-part questions

511. Answer a query containing multiple metrics.
512. Answer a query containing multiple dimensions.
513. Answer a query containing nested filters.
514. Answer a query with include and exclude filters.
515. Answer a query with top-N and bottom-N requirements.
516. Answer a query with sorting and pagination.
517. Answer a query requiring a period comparison.
518. Answer a query requiring percentage share.
519. Answer a query requiring contribution analysis.
520. Answer a query requiring a drill-down path.
521. Answer a query requiring records and aggregates together.
522. Answer a query spanning commerce and advertising.
523. Answer a query spanning campaign, order, order item, and city.
524. Split a query into multiple deterministic subqueries when a single Cube query cannot safely answer it.
525. Join subquery results only through approved keys and grain rules.
526. Warn about fan-out and double-counting risks.
527. Refuse an invalid metric-dimension combination.
528. Suggest the nearest supported alternative.

---

# 24. Access-control and privacy queries

529. Can I access customer-level records?
530. Can I access order-level records?
531. Can I export email addresses or phone numbers?
532. Can I see financial margin data?
533. Can I see data for all brands or only assigned brands?
534. Apply row-level security based on brand, account, geography, or team.
535. Mask restricted fields.
536. Return aggregates when row-level access is denied.
537. Explain which policy prevented a query.
538. Log every sensitive-data query.
539. Require elevated approval for bulk exports.
540. Prevent prompt instructions from bypassing access policy.
541. Prevent direct unrestricted SQL against ClickHouse.
542. Prevent access to hidden or internal Cube models.

---

# 25. Safe action discovery and preview

543. What actions can I perform?
544. What permissions are required for an action?
545. What fields are required for an action?
546. What validation rules apply?
547. What records would be changed?
548. Preview the requested action without executing it.
549. Show failed validations.
550. Show warnings and side effects.
551. Show before-and-after values.
552. Generate an idempotency key.
553. Require explicit confirmation for write actions.
554. Show the audit record after execution.
555. Retry safely without duplicating the action.
556. Roll back only when the backend action explicitly supports rollback.

---

# 26. Order actions

557. Update the status of selected orders.
558. Validate requester permission and order eligibility.
559. Preview all selected orders and proposed status changes.
560. Reject orders that violate business rules.
561. Execute only after explicit confirmation.
562. Record actor, timestamp, source query, before value, after value, and backend response.
563. Add or update an internal order note.
564. Add or remove an approved order tag.
565. Cancel an eligible order.
566. Trigger an approved refund workflow.
567. Update fulfilment status through the backend API.
568. Generate shipping documents through an approved integration.
569. Never directly write to ClickHouse analytical tables.

---

# 27. Advertising actions

570. Pause or activate a campaign, ad set, or ad.
571. Preview current status and requested status.
572. Update an approved budget within configured limits.
573. Reject budget changes outside policy.
574. Preview old budget, new budget, percentage change, and expected constraints.
575. Update bid or optimization settings only through typed contracts.
576. Retrieve platform action status.
577. Audit who changed what and when.
578. Use Pipeboard only for supported, predefined actions.
579. Never generate arbitrary platform API payloads from free-form LLM text.

---

# 28. Scheduled reports and alerts

580. Generate a daily business report.
581. Generate a daily pet-industry report when external news retrieval is integrated.
582. Generate a daily Meta Ads report.
583. Generate a weekly product-performance report.
584. Generate a monthly P&L report.
585. Alert when spend exceeds a threshold.
586. Alert when CPA exceeds a threshold.
587. Alert when ROAS falls below a threshold.
588. Alert when revenue drops beyond a configured baseline.
589. Alert when a product is near stockout.
590. Alert when a pipeline is stale.
591. Alert only when a condition is met; otherwise send nothing.
592. Include provenance and freshness in every report or alert.

---

# 29. Unsupported and adversarial query handling

593. Answer a request for a metric that does not exist.
594. Explain that the metric is unavailable instead of inventing it.
595. Answer a request for an unsupported dimension.
596. Answer a request requiring a missing join path.
597. Answer a request mixing incompatible grains.
598. Answer a request that would cause double counting.
599. Answer a request for future data not available in the database.
600. Answer a request for causal certainty that the data cannot establish.
601. Answer a request to ignore the catalogue formula.
602. Answer a request to use a hidden raw cube.
603. Answer a request to run arbitrary SQL.
604. Answer a request to bypass authorization.
605. Answer a request to execute an action without confirmation.
606. Answer a request containing an invalid entity name.
607. Return candidates and request disambiguation when necessary.
608. State the exact missing catalogue/model capability required to support the query.

---

# 30. Required canonical query families by domain

Every supported business metric should pass all applicable templates below:

609. Metric value for a selected period.
610. Metric trend over time.
611. Metric by every approved dimension.
612. Metric filtered by every approved dimension.
613. Metric compared with the previous period.
614. Metric compared year over year.
615. Metric share of total.
616. Metric contribution to change.
617. Metric top-N and bottom-N.
618. Metric anomaly detection.
619. Metric drill-down to the lowest approved grain.
620. Metric record traceability.
621. Metric definition and formula.
622. Metric source and Cube mapping.
623. Metric freshness and SLA.
624. Metric owner and access policy.
625. Metric validation test status.
626. Metric reconciliation against source totals.
627. Metric handling for partial current-day data.
628. Metric response under denied permissions.
629. Metric response when source data is stale.
630. Metric response when the requested combination is unsupported.

---

# 31. Mandatory end-to-end acceptance scenarios

## Scenario A: Executive summary

“Show today’s net revenue, orders, AOV, gross margin, ad spend, blended ROAS, and new-customer CAC. Compare them with yesterday and the same weekday last week. Explain only material changes and cite the contributing products, channels, and campaigns.”

## Scenario B: Campaign to order to city

“For campaign TH-383-SUSPENDER-20JUNE, list the orders attributed during the last 7 completed days, showing order ID, order date, net revenue, customer type, shipping city, state, attributed platform, campaign ID, campaign name, ad set, ad, and attribution model. Then summarize orders and revenue by city.”

Required model capability: an approved order-grain attribution view joined to canonical commerce orders, with stable order key, shipping city/state, campaign hierarchy, and an explicit attribution model.

## Scenario C: Profitability drill-down

“Show net revenue and gross margin by country for the last 90 days, compare with the previous 90 days, explain the main changes, and allow drill-down to order-item level.”

## Scenario D: Cross-channel reconciliation

“Compare Meta and Google reported purchases with canonical backend orders and attributed orders for the last 30 days. Quantify unmatched, duplicate, and unattributed orders.”

## Scenario E: Product opportunity

“Which products should we scale based on demand growth, contribution margin after ad spend, refund rate, inventory cover, and creative performance? Show the deterministic rules and evidence.”

## Scenario F: Safe order action

“Update the status of selected orders after validating permissions and business rules.”

Required sequence: resolve records → authorize → validate → preview → request confirmation → execute typed backend action → verify result → audit.

## Scenario G: Safe advertising action

“Raise the daily budget of eligible Meta campaigns by 15%, but only where backend ROAS, contribution margin, campaign age, frequency, and inventory cover meet approved rules. Preview only.”

## Scenario H: Data-quality refusal

“Give me today’s final revenue,” when today’s ingestion is incomplete. The MCP must identify incomplete data, label the value as partial, or refuse to call it final.

---

# 32. Catalogue fields required to support these queries

For every metric:

- `metric_id`
- `display_name`
- `description`
- `business_definition`
- `formula`
- `calculation_service`
- `canonical_cube_view`
- `canonical_measure`
- `grain`
- `additivity`
- `supported_dimensions`
- `supported_filters`
- `required_filters`
- `time_dimension`
- `default_timezone`
- `comparison_support`
- `drilldown_path`
- `record_entity`
- `source_models`
- `owner`
- `roles_allowed`
- `row_level_policy`
- `freshness_sla`
- `partial_day_policy`
- `validation_tests`
- `synonyms`
- `examples`
- `deprecated_by`

For every dimension:

- `dimension_id`
- `display_name`
- `definition`
- `data_type`
- `canonical_cube_view`
- `canonical_member`
- `grain`
- `join_entity`
- `filter_operators`
- `sensitive_classification`
- `roles_allowed`
- `synonyms`
- `examples`

For every record entity:

- `entity_id`
- `primary_key`
- `stable_business_key`
- `canonical_view`
- `grain`
- `available_fields`
- `allowed_joins`
- `drilldown_children`
- `sensitive_fields`
- `default_masking`
- `export_policy`

For every action:

- `action_id`
- `description`
- `typed_input_schema`
- `backend_mapping`
- `roles_allowed`
- `validation_rules`
- `preview_required`
- `confirmation_required`
- `idempotency_policy`
- `audit_policy`
- `side_effects`
- `rollback_support`

---

# 33. Priority implementation order

## P0 — Must work for MVP

- Catalogue and glossary discovery
- Revenue, orders, AOV, refunds, discounts, units
- Product and SKU performance
- Meta and Google spend/performance
- Canonical attribution metrics
- Date ranges and prior-period comparisons
- Brand/channel/product/campaign/country/state/city dimensions where data exists
- Order and order-item drill-down
- Campaign → attributed order → city join path
- Provenance, filters, metric definition, grain, and freshness
- Role-based access and row-level security
- Data-quality status and deterministic refusal
- Safe action discovery, preview, confirmation, execution, and audit

## P1 — Important next

- Customer cohorts and LTV
- Inventory and stockout analysis
- Logistics, NDR, RTO, and delivery performance
- P&L and contribution margin after ad spend
- Funnel analytics
- Marketplace reconciliation
- Deterministic anomaly detection and contribution analysis

## P2 — Defer until foundations are stable

- Predictive forecasting
- Recommendation optimization
- Autonomous budget changes
- Complex multi-touch attribution
- Cross-agent orchestration
- Unstructured document reasoning
- Vector-first metric resolution
- Autonomous multi-step actions without human approval

---

# 34. Definition of done for each query

A query capability is complete only when all of the following pass:

1. Intent is resolved to canonical catalogue IDs.
2. Entity names are resolved to stable IDs.
3. Metric-dimension compatibility is validated.
4. Grain and join path are validated.
5. Access policies are enforced before execution.
6. Cube or backend query is deterministic.
7. Numerical calculations are performed outside the LLM.
8. The result reconciles with known source totals.
9. Provenance, filters, timezone, grain, and freshness are returned.
10. Drill-down records reconcile to the aggregate.
11. Unsupported combinations fail clearly and safely.
12. Every action supports preview, confirmation, idempotency, and audit.

