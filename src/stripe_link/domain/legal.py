"""Platform legal pages (Terms, Privacy, Refund).

Platform-global content served at ``/legal/{page_id}`` and linked from storefront
footers. The three pages ship as built-in defaults templated from ``LEGAL_CONFIG`` so
the endpoint works with an empty table; a stored ``legal_page`` document may override
any field per page (title, link_text, display_order, enabled, content).

This module is pure -- no I/O. The handler supplies stored pages and the current year.
"""

from html import escape
from typing import Any

# Platform legal constants. In the legacy implementation these were app-config values
# that fell back to exactly these defaults; the platform never overrode them, so they
# are carried here as constants and can be lifted into config later without changing output.
LEGAL_CONFIG: dict[str, str] = {
    "company_name": "Junior Bay Corporation",
    "legal_address": "30 N Gould St, Ste R",
    "legal_city": "Cheyenne",
    "legal_state": "WY",
    "legal_zip": "82801",
    "legal_jurisdiction": "Laramie County, WY",
    "legal_email": "support@juniorbay.net",
    "website": "https://juniorbay.com",
    "legal_effective_date": "March 24, 2026",
    "legal_last_revised_date": "March 24, 2026",
}

LEGAL_PAGE_IDS = ("terms", "privacy", "refund")


def default_pages(config: dict[str, str] | None = None) -> list[dict[str, Any]]:
    cfg = {**LEGAL_CONFIG, **(config or {})}
    company_name = cfg["company_name"]
    website = cfg["website"]
    legal_email = cfg["legal_email"]
    legal_address = cfg["legal_address"]
    legal_city = cfg["legal_city"]
    legal_state = cfg["legal_state"]
    legal_zip = cfg["legal_zip"]
    legal_jurisdiction = cfg["legal_jurisdiction"]

    return [
        {
            "page_id": "terms",
            "title": "Terms of Service",
            "link_text": "Terms",
            "display_order": 10,
            "enabled": True,
            "content": f"""
                <p><strong>Please read carefully.</strong> These Terms of Service govern your access to and use of the {company_name} platform. By registering for, accessing, or using the service, you agree to be bound by these Terms. If you do not agree, you may not use the service.</p>
                <p>{company_name} provides a multi-tenant e-commerce platform that enables independent merchants to create branded storefronts and sell physical and digital products to their customers through related websites, including <a href="{website}">{website}</a>, related subdomains, APIs, checkout tools, and operational workflows.</p>
                <p>We may update these Terms from time to time. Material changes will be communicated through email or in-app notice at least fourteen (14) days before taking effect, except where a change is required by law or applies to new features and must take effect sooner. Continued use after updated Terms become effective constitutes acceptance.</p>
                <h2>1. Access and Use of the Service</h2>
                <h3>Service Description</h3>
                <p>{company_name} provides a hosted platform through which merchants may create and manage storefronts, list and sell physical or digital products, configure checkout flows, publish offers and upsells, and access tools for orders, shipping, and analytics. {company_name} is a technology platform and is not a party to transactions between merchants and buyers.</p>
                <h3>Eligibility</h3>
                <p>You must be at least 18 years old and legally capable of forming a binding contract to use the service. If you use the service on behalf of a business, you represent that you have authority to bind that business to these Terms.</p>
                <h3>Account Registration and Security</h3>
                <p>You must provide accurate, current, and complete account information and keep it updated. You are responsible for all activity under your account, for safeguarding your credentials, and for notifying us promptly at <a href="mailto:{legal_email}">{legal_email}</a> if you believe your account has been compromised.</p>
                <h3>Service Changes</h3>
                <p>We may modify, suspend, or discontinue any part of the service at any time. We will use reasonable efforts to provide notice of material changes, but we are not liable for modifications, suspensions, or discontinuations of the service.</p>
                <h2>2. Merchant Stores and Storefronts</h2>
                <h3>Merchant Responsibilities</h3>
                <p>Merchants are solely responsible for the accuracy, legality, safety, and fulfillment of all products, descriptions, prices, claims, images, and related storefront content. Merchants are also responsible for handling shipping, delivery, taxes, product compliance, and customer support obligations arising from their business.</p>
                <h3>Restricted Content and Products</h3>
                <p>You may not use the service to list or sell unlawful goods or services, counterfeit items, infringing materials, prohibited adult content, items that promote violence or hate, or any product or service prohibited by applicable law or our platform policies.</p>
                <h3>Custom Domains</h3>
                <p>If you connect a custom domain, you represent that you own or have the right to use that domain and that its use does not infringe third-party rights. {company_name} is not responsible for domain disputes, DNS propagation delays, registrar issues, or certificate problems outside our reasonable control.</p>
                <h3>Platform Neutrality</h3>
                <p>{company_name} does not pre-screen every listing and does not guarantee the legality, quality, safety, or fitness of any merchant product. We reserve the right, but not the obligation, to remove content or listings that violate these Terms or our policies.</p>
                <h2>3. Conditions of Use</h2>
                <h3>Prohibited Conduct</h3>
                <p>You agree not to use the service to violate applicable law, infringe third-party rights, upload malware, gain unauthorized access, scrape platform data without permission, engage in fraud, send spam, impersonate others, interfere with platform performance, or create duplicate or fake accounts to manipulate metrics or promotions.</p>
                <h3>Buyer Interactions</h3>
                <p>{company_name} is not a party to transactions between merchants and buyers. Merchants are solely responsible for product fulfillment, refunds, customer communications, and resolving customer disputes. We may facilitate resolution at our discretion, but we are not obligated to do so.</p>
                <h3>Compliance With Laws</h3>
                <p>You are solely responsible for complying with all laws applicable to your use of the service, including consumer protection, marketing, privacy, tax, export, and product safety laws. {company_name} does not provide legal, tax, or compliance advice.</p>
                <h2>4. Payments and Fees</h2>
                <h3>Platform Fees</h3>
                <p>{company_name} charges platform fees on transactions processed through the service, as described in your account dashboard or pricing terms. Fees may change upon notice. Continued use of the service after a fee change becomes effective constitutes acceptance of the updated fee structure.</p>
                <h3>Payment Processing</h3>
                <p>Payment processing is provided by Stripe through Stripe Connect. By accepting payments through the platform, you also agree to the applicable Stripe agreements, including the Stripe Connected Account Agreement and Stripe Services Agreement. {company_name} is not responsible for Stripe outages, errors, reserve actions, payout delays, or account restrictions imposed by Stripe.</p>
                <h3>Payouts, Reserves, and Availability</h3>
                <p>Merchant payouts are governed by the connected Stripe account and Stripe&apos;s payout schedule, reserve policies, review procedures, and availability windows. {company_name} does not directly hold merchant funds and does not control Stripe-initiated holds, reserves, or delayed availability.</p>
                <h3>Chargebacks, Refunds, and Disputes</h3>
                <p>Merchants are responsible for refunds, chargebacks, disputes, and losses associated with their transactions. We may recover previously credited platform fees or other amounts when transactions are reversed, refunded, disputed, or found to violate these Terms or applicable policies.</p>
                <h3>Subscriptions</h3>
                <p>If you subscribe to a paid plan, the subscription renews automatically at the then-current rate unless cancelled before the renewal date. You authorize us to charge any payment method on file for renewal fees. Paid subscription fees are non-refundable except where required by law or expressly stated otherwise.</p>
                <h2>5. Intellectual Property</h2>
                <h3>Platform Intellectual Property</h3>
                <p>The platform, including its software, code, designs, trademarks, logos, and related content, is owned by {company_name} or its licensors and is protected by intellectual property law. You may not copy, reverse engineer, decompile, resell, or create derivative works from the platform except as expressly permitted in writing.</p>
                <h3>Merchant Content License</h3>
                <p>You retain ownership of the content you upload, including product descriptions, images, and branding. You grant {company_name} a non-exclusive, worldwide, royalty-free license to host, store, display, transmit, reproduce, and process that content solely as necessary to operate, improve, and provide the service.</p>
                <h3>Feedback</h3>
                <p>If you submit suggestions, ideas, or feedback, you agree that we may use that feedback for any lawful purpose without restriction, compensation, or attribution.</p>
                <h3>Copyright Complaints</h3>
                <p>If you believe content on the platform infringes your intellectual property rights, contact us at <a href="mailto:{legal_email}">{legal_email}</a> with sufficient detail for us to review and respond to the complaint.</p>
                <h2>6. Third-Party Services</h2>
                <p>The service may integrate with or depend on third-party services, including Stripe, shipping providers, analytics providers, domain services, and communication providers. Your use of third-party services is governed by their own terms and policies, and {company_name} is not responsible for their performance, availability, or conduct.</p>
                <h2>7. Indemnity</h2>
                <p>You agree to indemnify, defend, and hold harmless {company_name}, its affiliates, officers, directors, employees, and agents from and against claims, damages, liabilities, losses, costs, and expenses, including reasonable attorneys&apos; fees, arising out of or related to your use of the service, your products, your content, your violation of these Terms, your violation of law, or disputes between you and buyers or other third parties.</p>
                <h2>8. Disclaimer of Warranties</h2>
                <p><strong>THE SERVICE IS PROVIDED ON AN &quot;AS IS&quot; AND &quot;AS AVAILABLE&quot; BASIS.</strong> TO THE MAXIMUM EXTENT PERMITTED BY LAW, {company_name.upper()} DISCLAIMS ALL WARRANTIES, WHETHER EXPRESS, IMPLIED, OR STATUTORY, INCLUDING WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, AND NON-INFRINGEMENT. WE DO NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED, ERROR-FREE, OR SECURE.</p>
                <h2>9. Limitation of Liability</h2>
                <p>To the maximum extent permitted by law, {company_name} will not be liable for indirect, incidental, special, consequential, exemplary, or punitive damages, including lost profits, lost revenue, lost data, or loss of goodwill arising from or related to your use of the service. In no event will our aggregate liability exceed the greater of the fees paid by you to {company_name} in the six (6) months preceding the claim or one hundred dollars (USD $100).</p>
                <h2>10. Dispute Resolution and Arbitration</h2>
                <p>Please read this section carefully. It requires binding arbitration of most disputes and waives the right to a jury trial and class action participation.</p>
                <p>Any dispute arising out of or relating to these Terms or the service will be resolved by binding arbitration, except that either party may bring an eligible claim in small claims court. Claims may be brought only on an individual basis and not as part of a class or representative proceeding. These Terms are governed by the laws of the State of Wyoming, without regard to conflict-of-law principles. For disputes not subject to arbitration, venue is in the state or federal courts located in {legal_jurisdiction}.</p>
                <h2>11. Termination</h2>
                <p>We may suspend or terminate access to the service at any time, with or without notice, for any reason, including violation of these Terms, suspected fraud, legal risk, or operational necessity. You may stop using the service at any time. Provisions that by their nature should survive termination will survive, including those related to fees, intellectual property, indemnity, disclaimers, liability, and dispute resolution.</p>
                <h2>12. General Provisions</h2>
                <p>These Terms, together with the Privacy Policy and any supplemental terms applicable to specific features, constitute the entire agreement between you and {company_name} regarding the service. If any provision is found unenforceable, the remaining provisions remain in effect. A failure to enforce any provision is not a waiver. You may not assign these Terms without our written consent, but we may assign them in connection with a merger, acquisition, financing, or sale of assets.</p>
                <h2>13. Contact</h2>
                <p>Questions, concerns, or legal notices regarding these Terms may be directed to:</p>
                <p>{company_name}<br>{legal_address}<br>{legal_city}, {legal_state} {legal_zip}<br><a href="mailto:{legal_email}">{legal_email}</a></p>
            """.strip(),
        },
        {
            "page_id": "privacy",
            "title": "Privacy Policy",
            "link_text": "Privacy",
            "display_order": 20,
            "enabled": True,
            "content": f"""
                <p><strong>Your privacy matters to us.</strong> This Privacy Policy explains what personal information {company_name} collects, how we use it, and the choices you have. By using the {company_name} platform, you agree to the practices described here.</p>
                <p>{company_name} operates a multi-tenant e-commerce platform that enables independent merchants to create branded online stores and sell physical and digital products to their customers. This Privacy Policy applies to merchants, buyers, and visitors who use {website}, related subdomains, hosted storefronts, checkouts, and associated platform tools.</p>
                <p>{company_name} is the controller of personal information collected directly through the platform. If you have questions about this Privacy Policy, contact us at <a href="mailto:{legal_email}">{legal_email}</a>.</p>
                <h2>Information We Collect</h2>
                <h3>Information You Provide</h3>
                <p>We collect information you provide directly when you register, configure your account, create storefront content, make a purchase, connect a custom domain, or contact support.</p>
                <ul>
                    <li><strong>Account and profile information:</strong> name, email address, phone number, business name, and account preferences.</li>
                    <li><strong>Store and merchant content:</strong> product listings, descriptions, pricing, images, offer configurations, landing page content, and business branding.</li>
                    <li><strong>Order and fulfillment information:</strong> buyer names, shipping addresses, email addresses, and purchase details needed to process and fulfill orders.</li>
                    <li><strong>Support and communications:</strong> information you share when contacting us, responding to surveys, or interacting with platform support.</li>
                    <li><strong>Domain and configuration data:</strong> custom domain details, DNS information, tax and shipping settings, and other configuration data you choose to store in the platform.</li>
                </ul>
                <h3>Information We Collect Automatically</h3>
                <p>When you access or use the service, we automatically collect certain technical and usage information.</p>
                <ul>
                    <li><strong>Log data:</strong> IP address, browser type and version, page visits, timestamps, and referring URLs.</li>
                    <li><strong>Device information:</strong> device type, operating system, browser settings, and general diagnostic data.</li>
                    <li><strong>Usage information:</strong> features used, actions taken, session duration, navigation patterns, and interaction history within the platform.</li>
                    <li><strong>Cookies and similar technologies:</strong> cookies and similar tools used to operate the service, remember preferences, support authentication, and analyze usage.</li>
                    <li><strong>Location information:</strong> general geographic location inferred from IP address.</li>
                    <li><strong>Email engagement information:</strong> whether emails we send are opened or links are clicked, where standard tracking tools are used.</li>
                </ul>
                <h3>Information from Third Parties</h3>
                <p>We may receive limited information from third parties, including fraud prevention and payment status information from Stripe, publicly available business verification information, and information from third-party services you choose to connect.</p>
                <h2>How We Use Your Information</h2>
                <p>We use the information we collect to operate, improve, secure, and support the platform.</p>
                <ul>
                    <li>Provide and operate the platform, including authentication, storefront hosting, checkout, order processing, and customer support.</li>
                    <li>Improve the service through analytics, diagnostics, feature development, testing, and product research.</li>
                    <li>Personalize the user experience by remembering preferences, showing relevant content, and supporting merchant-specific configuration.</li>
                    <li>Send transactional and operational communications, including receipts, order notifications, security alerts, legal notices, and policy updates.</li>
                    <li>Send promotional communications about {company_name} features or offers, where permitted by law and subject to opt-out rights.</li>
                    <li>Protect the security and integrity of the platform, prevent fraud, and enforce our terms, policies, and agreements.</li>
                    <li>Comply with legal obligations, resolve disputes, and support audits, regulatory requests, or lawful government demands.</li>
                    <li>Support business transitions, including due diligence, mergers, restructurings, financing events, or asset sales.</li>
                </ul>
                <h3>Aggregated and De-Identified Data</h3>
                <p>We may create aggregated, de-identified, or anonymized information that does not reasonably identify an individual. We may use such information for analytics, research, benchmarking, and other lawful business purposes.</p>
                <h3>Marketing Opt-Out</h3>
                <p>You may opt out of marketing emails at any time by using the unsubscribe link in the email or by contacting us at <a href="mailto:{legal_email}">{legal_email}</a>. Opting out does not affect transactional or account-related communications.</p>
                <h2>Sharing and Disclosure of Information</h2>
                <p>We do not sell personal information. We may disclose information in the following circumstances:</p>
                <ul>
                    <li><strong>Service providers:</strong> vendors who support hosting, payment processing, analytics, communications, security, customer support, and operational infrastructure.</li>
                    <li><strong>Payment processor:</strong> Stripe processes payments and may act as an independent controller for certain payment-related data. Review Stripe&apos;s privacy practices at <a href="https://stripe.com/privacy" target="_blank" rel="noopener noreferrer">https://stripe.com/privacy</a>.</li>
                    <li><strong>Legal requirements:</strong> when required by law, subpoena, court order, lawful government request, or to protect rights, property, safety, or platform integrity.</li>
                    <li><strong>Business transfers:</strong> in connection with a merger, acquisition, financing, restructuring, bankruptcy, or sale of assets.</li>
                    <li><strong>With your consent:</strong> where you direct us to share information for a specific purpose.</li>
                    <li><strong>Aggregated or anonymized disclosures:</strong> where the data cannot reasonably identify you.</li>
                </ul>
                <h2>Merchant Storefront Data</h2>
                <p>When a buyer places an order on a merchant storefront, the merchant receives the buyer&apos;s order information, including contact details, shipping information, and purchase details needed to fulfill the order and communicate with the buyer.</p>
                <p>Merchants operate their storefronts independently. {company_name} is not responsible for how individual merchants use information they receive from buyers through their storefronts. Buyers should review merchant-specific policies where applicable before purchasing.</p>
                <p>Merchants are responsible for complying with applicable privacy and marketing laws in connection with buyer data they receive through the platform.</p>
                <h2>Your Rights and Choices</h2>
                <p>Depending on your location and applicable law, you may have rights regarding your personal information, including the right to access, correct, delete, restrict, object to certain processing, or request portability of your data.</p>
                <p>To exercise applicable rights, contact us at <a href="mailto:{legal_email}">{legal_email}</a>. We may need to verify your identity before processing your request. We will respond within the timeframe required by applicable law.</p>
                <h3>Cookies and Tracking</h3>
                <p>You can control cookies through your browser settings. Blocking or deleting cookies may affect platform functionality. We do not currently guarantee a response to browser &quot;Do Not Track&quot; signals.</p>
                <h3>California Residents</h3>
                <p>If you are a California resident, you may have additional rights under the California Consumer Privacy Act and related laws. {company_name} does not sell personal information. To submit an applicable request, contact us at <a href="mailto:{legal_email}">{legal_email}</a>.</p>
                <h2>Children</h2>
                <p>The service is not directed to children under 16, and we do not knowingly collect personal information from children under 16. If you believe a child has submitted personal information to us, please contact <a href="mailto:{legal_email}">{legal_email}</a> so we can review and delete the information where appropriate.</p>
                <h2>Third-Party Links</h2>
                <p>The platform may contain links to third-party websites, merchant storefronts, or services that are not operated by {company_name}. We are not responsible for the privacy practices of those third parties and encourage you to review their policies separately.</p>
                <h2>Security</h2>
                <p>{company_name} uses commercially reasonable technical and organizational safeguards designed to protect personal information, including access controls, encrypted transmission where appropriate, and operational monitoring. No method of storage or transmission is completely secure, and we cannot guarantee absolute security.</p>
                <p>You are responsible for safeguarding your account credentials and promptly notifying us at <a href="mailto:{legal_email}">{legal_email}</a> if you suspect unauthorized account access.</p>
                <h2>International Users</h2>
                <p>{company_name} is based in the United States, and personal information may be stored and processed in the United States or other locations where our service providers operate. If you use the service from outside the United States, your information may be transferred to jurisdictions with different data protection laws than those in your home jurisdiction.</p>
                <h2>Changes to This Policy</h2>
                <p>We may update this Privacy Policy from time to time to reflect changes in our practices, legal requirements, or platform features. When material changes are made, we will update this page and may provide notice by email or through the platform where appropriate. Continued use of the service after changes become effective constitutes acceptance of the updated policy.</p>
                <h2>Contact Us</h2>
                <p>If you have questions, concerns, or requests regarding this Privacy Policy or our information practices, contact us at:</p>
                <p>{company_name}<br>{legal_address}<br>{legal_city}, {legal_state} {legal_zip}<br><a href="mailto:{legal_email}">{legal_email}</a><br><a href="{website}">{website}</a></p>
                <p>We will make reasonable efforts to respond within an appropriate timeframe and, where required, within the period mandated by applicable law.</p>
            """.strip(),
        },
        {
            "page_id": "refund",
            "title": "Refund Policy",
            "link_text": "Refunds",
            "display_order": 30,
            "enabled": True,
            "content": f"""
                <p><strong>Important:</strong> {company_name} is a platform that enables independent merchants to sell products to buyers. Most refund and return decisions are governed by the individual merchant&apos;s policy. This page explains how the {company_name} platform supports dispute resolution and where our policies apply.</p>
                <h2>1. How {company_name} Works</h2>
                <p>{company_name} provides technology infrastructure that allows independent merchants to build and operate branded online storefronts. {company_name} is not the seller of record for products listed by merchants, and sales are transactions directly between the merchant and the buyer.</p>
                <p>Because merchants set their own return, refund, and cancellation policies, the terms displayed at checkout on each merchant storefront govern the purchase. {company_name} may intervene in specific circumstances described in this policy, but cannot override a merchant&apos;s legitimate policy decisions in cases outside our dispute process.</p>
                <p><strong>Always review the merchant&apos;s refund policy before purchasing.</strong> Each merchant&apos;s policy should be displayed on their storefront and at checkout. {company_name} requires merchants to make their policies clearly visible prior to purchase.</p>
                <h2>2. Reporting an Order Problem</h2>
                <p>If you experience an issue with an order, please follow these steps:</p>
                <ol>
                    <li><strong>Contact the merchant first.</strong> Use the storefront contact method or any order-help option provided through the platform. Allow the merchant at least 72 hours to respond and attempt to resolve the issue.</li>
                    <li><strong>Escalate to support.</strong> If the merchant does not respond within 72 hours or the issue remains unresolved, contact {company_name} Support at <a href="mailto:{legal_email}">{legal_email}</a> with your order number, a description of the issue, and any supporting documentation.</li>
                    <li><strong>Case review.</strong> {company_name} may request additional information from both the buyer and the merchant and aims to respond to escalated disputes within 5 business days.</li>
                    <li><strong>Resolution.</strong> If {company_name} determines that a refund is warranted under this policy, the merchant will be required to issue the refund or otherwise resolve the matter as directed by the platform.</li>
                </ol>
                <p><strong>Unless otherwise specified, all refunds are subject to a 30-day, no questions asked, money-back guarantee.</strong> Platform-assisted refunds are generally available for 30 days from the date of transaction. After 30 days, {company_name} may be unable to facilitate a platform refund, though the buyer may still attempt to resolve the matter directly with the merchant.</p>
                <h2>3. Refunds and Returns</h2>
                <h3>Merchant Refund Policies</h3>
                <p>Each merchant sets their own refund and return policy, which should be displayed on their storefront and at checkout. Merchants are expected to honor the policies they publish. If a merchant fails to honor a clearly stated policy, {company_name} may intervene.</p>
                <h3>Where {company_name} May Support Refunds</h3>
                <p>If a refund is approved through the platform dispute process, the refund will generally be issued back to the original form of payment. Processing times vary by bank or card issuer and are typically 5 to 10 business days. If a refund to the original method is not possible, {company_name} may permit platform credit at its discretion.</p>
                <h3>EU and International Withdrawal Rights</h3>
                <p>Where required by applicable law, including certain EU consumer protection rules, buyers may have the right to withdraw from a purchase within 14 days of the transaction date without providing a reason. That right may not apply to digital goods or services where immediate access was provided after any required waiver.</p>
                <h3>Physical Product Returns</h3>
                <p>Return eligibility and shipping responsibility for physical goods are determined by the individual merchant&apos;s policy. {company_name} does not warehouse, ship, or take physical possession of merchant products and therefore does not accept physical returns directly.</p>
                <p><strong>Stripe fees and platform fees are non-refundable.</strong> Stripe payment processing fees and {company_name} platform fees are non-refundable in all circumstances.</p>
                <h2>4. Non-Delivery and Not-as-Described Claims</h2>
                <p>{company_name} may require a merchant to issue a full refund, including applicable shipping charges, if any of the following conditions are met:</p>
                <ul>
                    <li><strong>Non-delivery:</strong> the order was not delivered and the merchant cannot provide valid proof of delivery.</li>
                    <li><strong>Significantly not as described:</strong> the item received differs materially from the listing description, photographs, or specifications shown at the time of purchase.</li>
                    <li><strong>Late delivery for time-sensitive orders:</strong> the item arrived after a critical deadline, where the deadline was communicated in writing before purchase and adequate proof is provided.</li>
                </ul>
                <p>If {company_name} determines a claim is valid under these standards, the merchant may be required to refund the order in full, including shipping charges where applicable. Submit such claims to <a href="mailto:{legal_email}">{legal_email}</a> with the order number and supporting evidence.</p>
                <h2>5. Ineligible Disputes</h2>
                <p>The platform dispute process is intended for genuine delivery and product issues. The following are generally outside the scope of the platform dispute system:</p>
                <ul>
                    <li>damage caused by the shipping carrier where the item was properly packaged;</li>
                    <li>items that have been altered, used, or consumed;</li>
                    <li>shipping delays that do not meet the time-sensitive criteria;</li>
                    <li>returns initiated without merchant agreement;</li>
                    <li>items accurately described but that did not meet personal expectations;</li>
                    <li>buyer&apos;s remorse or change of mind, unless covered by the merchant&apos;s stated policy;</li>
                    <li>disputes submitted after the 30-day platform window.</li>
                </ul>
                <p>Filing a chargeback with a bank or card issuer without first going through {company_name}&apos;s dispute process may result in account restrictions. Contact us first so we can attempt to resolve the issue fairly.</p>
                <h2>6. Digital Products</h2>
                <p>Digital products, including downloadable files, access keys, online courses, e-books, and software licenses, are generally non-refundable once delivered or accessed unless the merchant&apos;s policy states otherwise or applicable law requires a refund.</p>
                <h3>Immediate Access Waiver</h3>
                <p>At checkout, buyers purchasing digital products may be asked to acknowledge a waiver of any statutory withdrawal right in exchange for immediate access. Once access has been granted following such a waiver, a refund will generally not be issued on the basis of that withdrawal right alone.</p>
                <h3>Defective or Non-Functional Digital Products</h3>
                <p>If a digital product is defective, inaccessible, or materially different from its description, the buyer should contact the merchant within 72 hours of purchase. If the merchant cannot resolve the issue, the buyer may escalate to <a href="mailto:{legal_email}">{legal_email}</a> within the 30-day platform dispute window.</p>
                <h2>7. Cancellations</h2>
                <p>Only merchants can cancel confirmed transactions. If you wish to cancel an order, contact the merchant directly before the order is fulfilled, shipped, or digitally delivered. Whether a cancellation is accepted is subject to the merchant&apos;s stated cancellation policy.</p>
                <h2>8. Subscriptions</h2>
                <p>If you purchase a recurring subscription through a merchant storefront on {company_name}, subscriptions automatically renew at the end of each billing cycle unless cancelled before renewal. Refunds for subscription charges are subject to the merchant&apos;s subscription cancellation policy. {company_name} does not pro-rate partial billing periods unless the merchant&apos;s policy expressly provides for it.</p>
                <p>Stripe payment processing fees and {company_name} platform fees charged in connection with subscription transactions are non-refundable.</p>
                <h2>9. Fees and Processing Costs</h2>
                <p>Stripe payment processing fees and {company_name} platform fees are non-refundable under all circumstances, including where a buyer receives a refund. Those fees are incurred at the time of the original transaction and generally cannot be recovered by {company_name} or the merchant.</p>
                <p>In the event of a refund, the buyer receives the refundable portion of the purchase price, while Stripe&apos;s processing fee and the {company_name} platform fee are not returned. Merchants are responsible for absorbing these non-refundable costs unless otherwise agreed in writing with {company_name}.</p>
                <h2>10. Contact and Support</h2>
                <p>For order issues, refund requests, and dispute escalations, contact {company_name} Support and include the order number, a clear description of the issue, and any supporting documentation.</p>
                <p>{company_name}<br>{legal_address}<br>{legal_city}, {legal_state} {legal_zip}<br><a href="mailto:{legal_email}">{legal_email}</a><br><a href="{website}">{website}</a></p>
                <p>We aim to respond to support inquiries within 2 business days and to escalated disputes within 5 business days.</p>
            """.strip(),
        },
    ]


def _default_page_map(config: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    return {page["page_id"]: page for page in default_pages(config)}


def merge_page_with_default(
    page_id: str, stored: dict[str, Any] | None, config: dict[str, str] | None = None
) -> dict[str, Any] | None:
    """Overlay a stored legal_page document on its built-in default, filling empty fields."""
    default_page = _default_page_map(config).get(page_id)
    if not default_page and not stored:
        return None
    if not default_page:
        return stored
    if not stored:
        return default_page
    merged = {**default_page, **stored}
    if not merged.get("content"):
        merged["content"] = default_page.get("content", "")
    if not merged.get("title"):
        merged["title"] = default_page.get("title", "")
    if not merged.get("link_text"):
        merged["link_text"] = default_page.get("link_text", merged.get("title", ""))
    return merged


def pages_with_defaults(
    stored_pages: list[dict[str, Any]] | None, config: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """All enabled legal pages: built-in defaults overlaid with any stored overrides, ordered."""
    stored = {str(page.get("page_id")): page for page in (stored_pages or []) if page.get("page_id")}
    page_ids = set(stored) | set(_default_page_map(config))
    merged = [merge_page_with_default(page_id, stored.get(page_id), config) for page_id in page_ids]
    pages = [page for page in merged if page and page.get("enabled", True)]
    pages.sort(key=lambda page: page.get("display_order", 999))
    return pages


def render_public_page(page: dict[str, Any], config: dict[str, str] | None = None, current_year: int = 0) -> str:
    cfg = {**LEGAL_CONFIG, **(config or {})}
    title = escape(str(page.get("title", "Legal Page")))
    content = str(page.get("content", ""))
    company_name = escape(cfg["company_name"])
    effective_date = escape(cfg["legal_effective_date"])
    last_revised_date = escape(cfg["legal_last_revised_date"])
    footer_links = "".join(
        f'<a href="/legal/{page_id}">{escape(label)}</a>'
        for page_id, label in (("terms", "Terms"), ("privacy", "Privacy"), ("refund", "Refunds"))
    )
    year = current_year or ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light; --bg:#f7f7fb; --surface:#fff; --text:#1f2937; --muted:#6b7280; --line:#e5e7eb; --accent:#4f46e5; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:linear-gradient(180deg,#fbfbff 0%,var(--bg) 100%); color:var(--text); }}
    .wrap {{ max-width:860px; margin:0 auto; padding:40px 20px 56px; }}
    .card {{ background:var(--surface); border:1px solid var(--line); border-radius:16px; overflow:hidden; }}
    .hero {{ padding:32px 28px 20px; border-bottom:1px solid var(--line); }}
    .eyebrow {{ text-transform:uppercase; letter-spacing:.08em; font-size:12px; font-weight:700; color:var(--accent); margin:0 0 8px; }}
    h1 {{ margin:0 0 8px; font-size:34px; line-height:1.15; }}
    .company {{ margin:0; color:var(--muted); font-weight:600; }}
    .hero-meta {{ display:flex; flex-wrap:wrap; gap:16px; margin-top:14px; font-size:14px; color:var(--muted); }}
    .hero-meta strong {{ color:var(--text); }}
    .content {{ padding:28px; line-height:1.7; font-size:16px; }}
    .content h2 {{ margin-top:28px; margin-bottom:10px; font-size:20px; line-height:1.3; }}
    .content h3 {{ margin-top:20px; margin-bottom:8px; font-size:17px; }}
    .content p, .content li {{ margin:0 0 12px; color:var(--text); }}
    .content a {{ color:var(--accent); }}
    .footer {{ padding:20px 28px 28px; border-top:1px solid var(--line); display:flex; flex-wrap:wrap; gap:16px; align-items:center; justify-content:space-between; }}
    .links {{ display:flex; gap:18px; flex-wrap:wrap; }}
    .links a {{ color:var(--accent); text-decoration:none; font-weight:600; }}
    .links a:hover {{ text-decoration:underline; }}
    .copy {{ color:var(--muted); font-size:14px; }}
    @media (max-width:640px) {{ .wrap {{ padding:24px 16px 40px; }} h1 {{ font-size:28px; }} .footer {{ flex-direction:column; align-items:flex-start; }} }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="card">
      <header class="hero">
        <p class="eyebrow">Legal</p>
        <h1>{title}</h1>
        <p class="company">{company_name}</p>
        <div class="hero-meta">
          <div><strong>Effective:</strong> {effective_date}</div>
          <div><strong>Last Revised:</strong> {last_revised_date}</div>
        </div>
      </header>
      <article class="content">
        {content}
      </article>
      <footer class="footer">
        <nav class="links">{footer_links}</nav>
        <div class="copy">&copy; {year} {company_name}. All rights reserved.</div>
      </footer>
    </section>
  </main>
</body>
</html>"""
