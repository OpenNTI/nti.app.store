${site_alias} CUSTOMER RECEIPT
Date ${today}

Transaction ID: ${transaction_id}


Billed to:
${billed_to}
${nti_context.charge.Address}

%for item in nti_context.purchase.Order.Items:
${item.Quantity}x ${item.purchasable.Title} - ${format_currency_attribute(item.purchasable, 'Amount')} each
%if item.purchasable.License:
	(${item.purchasable.License})
%endif
% if redeem_by_clause:
	${redeem_by_clause}.
% endif
%if item.Quantity > 1:
	Activation Key: ${transaction_id}
%endif
%endfor

Subtotal: ${format_currency_attribute(nti_context.purchase.Pricing, 'TotalNonDiscountedPrice')}
## XXX: JAM: Not sure how to figure out the discounts. I'm just deriving them...
%if nti_context.purchase.Pricing.TotalNonDiscountedPrice and nti_context.purchase.Pricing.TotalPurchasePrice < nti_context.purchase.Pricing.TotalNonDiscountedPrice:
Discount(${nti_context.purchase.Order.Coupon}): ${formatted_discount}
%endif

ORDER TOTAL: ${format_currency_attribute(nti_context.charge, 'Amount')}


Payment Received: ${format_currency_attribute(nti_context.charge, 'Amount')}
${today} (**** **** **** ${nti_context.charge.CardLast4})
all sales are final


Thank you for your order, ${informal_username}! Your Items are available at ${request.application_url}


Please keep a copy of this receipt for your records.
If you have any questions, feel free to contact ${support_email}
