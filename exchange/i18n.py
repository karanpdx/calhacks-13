"""Borrower presentation catalog. Add a language dictionary, never translate protocol data.

Spanish copy is machine-assisted. USD remains USD in every language. Context is
request-local (including worker threads), and is always reset after a presentation.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import re

LANGUAGES = ("en", "es")
_LANG = ContextVar("borrower_language", default="en")

# English templates are the stable lookup keys. All visible borrower copy lives here.
ES = {
    "Checking won't affect your credit score.": "Esta consulta no afecta tu puntaje de crédito.",
    "Lenders see a summary, never your name, SSN or address.": "Los prestamistas ven un resumen, nunca tu nombre, número de Seguro Social ni dirección.",
    "{v0} months": "{v0} meses",
    "{v0} to {v1} months": "De {v0} a {v1} meses",
    "Your agent saved you ${v0} compared with the best first offer ({v1}% from {v2}).": "Tu agente te ahorró {v0} USD frente a la mejor oferta inicial ({v1}% de {v2}).",
    "{v0} lends you {v1}: {v2} a month for {v3} months.": "{v0} te presta {v1}: pagas {v2} al mes durante {v3} meses.",
    "Agreed to autopay (payments come out automatically each month), which lowered the rate.": "Aceptó pagos automáticos cada mes para bajar la tasa.",
    "Agreed to autopay (payments come out automatically each month).": "Aceptó pagos que se cobran de forma automática cada mes.",
    "Took a longer loan ({v0} months instead of {v1}), so you pay for longer.": "Eligió un préstamo más largo ({v0} meses en vez de {v1}). Pagarás durante más tiempo.",
    "Took the full {v0} at {v1}% instead of {v2} at {v3}% from {v4}.": "Eligió el monto completo de {v0} al {v1}%, en vez de {v2} al {v3}% de {v4}.",
    "Borrowing {v0} instead of the {v1} you asked for.": "Recibirás {v0} en vez de los {v1} que pediste.",
    "Pays a one-time {v0} fee, which is inside your limit.": "Pagarás un cargo único de {v0}. Está dentro de tu límite.",
    "because there's a fraud alert on your file": "porque hay una alerta de fraude en tu historial",
    "because some identity details need a second look": "porque hay datos de identidad que debemos revisar",
    "First you confirm it's really you, with a few questions or a code, {v0}.": "Primero confirmas tu identidad con unas preguntas o un código, {v0}.",
    "{v0} runs a hard credit check. Your score may dip a few points.": "{v0} hace una consulta completa de crédito. Tu puntaje puede bajar unos puntos.",
    "{v0} gets your full credit file.": "{v0} recibe tu informe de crédito completo.",
    "{v0} sends you {v1}.": "{v0} te envía {v1}.",
    "The new loan shows up at all three credit bureaus. Paying on time builds your credit.": "El préstamo aparece en las tres agencias de crédito. Pagar a tiempo ayuda a crear tu historial.",
    "bank login": "datos de acceso al banco", "date of birth": "fecha de nacimiento", "SSN": "número de Seguro Social",
    "{v0} tried to trick your agent with hidden instructions. We removed it.": "{v0} intentó engañar a tu agente con instrucciones ocultas. Lo retiramos del mercado.",
    "Some lenders' agents hide commands in their messages. Here only the loan's numbers count, so it couldn't make your agent say yes.": "Algunos agentes ocultan órdenes en sus mensajes. Aquí solo cuentan las cifras del préstamo. Esas órdenes no pueden hacer que tu agente acepte.",
    "{v0} tried to swap in a worse deal after making an offer. We removed it.": "{v0} intentó empeorar una oferta que ya había hecho. Lo retiramos del mercado.",
    "Once a lender makes an offer here, it can't raise the price. It can only offer you something better.": "Después de hacer una oferta, un prestamista no puede subir el costo. Solo puede mejorarla.",
    "{v0} sent a message pretending to be someone else. We removed it.": "{v0} envió un mensaje haciéndose pasar por otra persona. Lo retiramos del mercado.",
    "Every message is checked to prove who sent it, so fakes don't count.": "Revisamos quién envió cada mensaje. Los mensajes falsos no cuentan.",
    "{v0} broke the exchange's rules. We removed it.": "{v0} rompió las reglas del mercado. Lo retiramos.",
    "Its offers were taken away and it couldn't send anything else.": "Retiramos sus ofertas y bloqueamos sus mensajes.",
    "{v0}'s offer": "la oferta de {v0}", "an offer": "una oferta",
    "Someone tried to accept {v0} while pretending to be your agent. We blocked it.": "Alguien intentó aceptar {v0} haciéndose pasar por tu agente. Lo bloqueamos.",
    "Only your agent can say yes for you, and every message is checked to prove who sent it.": "Solo tu agente puede aceptar por ti. Revisamos quién envió cada mensaje.",
    "A fake message claiming to be from {v0} was blocked.": "Bloqueamos un mensaje falso que decía ser de {v0}.",
    "{v0} tried to swap in a worse deal after making an offer. We blocked it.": "{v0} intentó empeorar una oferta que ya había hecho. Lo bloqueamos.",
    "Your agent tried to accept a loan outside your limits. We blocked it.": "Tu agente intentó aceptar un préstamo fuera de tus límites. Lo bloqueamos.",
    "Your limits are enforced by the exchange, not by the agent. But this agent may not be working for you, so be careful trusting it.": "El mercado hace cumplir tus límites. Este agente quizá no esté cuidando tus intereses. Ten cuidado al confiar en él.",
    "{v0} tried to trick your agent with hidden instructions. We ignored them.": "{v0} intentó engañar a tu agente con instrucciones ocultas. Las ignoramos.",
    "Here only the loan's numbers count, so hidden instructions can't make your agent say yes.": "Aquí solo cuentan las cifras del préstamo. Las instrucciones ocultas no pueden hacer que tu agente acepte.",
    "Your agent sent a message with hidden instructions in it.": "Tu agente envió un mensaje con instrucciones ocultas.",
    "Only the loan's numbers count here, so the words can't change anything. Keep an eye on this agent.": "Aquí solo cuentan las cifras del préstamo. El texto no puede cambiarlas. Vigila a este agente.",
    "personal details": "datos personales", "it": "ese dato", "them": "esos datos",
    "{v0} asked for your {v1}. Never share {v2}.": "{v0} pidió estos datos: {v1}. Nunca compartas {v2}.",
    "Lenders here never need these to make an offer. Asking for them is a common scam. If you accept a deal, the lender gets your file through the exchange, not from you.": "Los prestamistas no necesitan estos datos para hacer una oferta. Pedirlos puede ser una estafa. Si aceptas, el mercado les entrega tu informe de forma segura.",
    "{v0} said the deal was the same but quietly raised the price.": "{v0} dijo que la oferta era igual, pero subió el costo sin avisar.",
    "Only the numbers in an offer count, not what the message says. Our rules caught the change.": "Solo cuentan las cifras de la oferta. Nuestras reglas detectaron el cambio.",
    "{v0} mentioned a fee that isn't in its offer.": "{v0} mencionó un cargo que no aparece en su oferta.",
    "Only fees written into the offer count. If anyone adds a fee later, you don't have to agree.": "Solo cuentan los cargos escritos en la oferta. No tienes que aceptar cargos nuevos.",
    "{v0}'s message named a different rate than its real offer.": "El mensaje de {v0} decía una tasa distinta a la de su oferta real.",
    "Trust the numbers in the offer, not the sales message.": "Revisa las cifras de la oferta. El mensaje de venta puede ser distinto.",
    "Your agent picked a pricier offer when a cheaper one fit your limits.": "Tu agente eligió una oferta más cara, aunque otra más barata cumplía tus límites.",
    "That costs you about {v0} more over the loan.": "Eso te cuesta unos {v0} más en todo el préstamo.",
    "That costs you more over the loan.": "Eso aumenta el costo total del préstamo.",
    "Your agent told lenders the highest rate you'd accept.": "Tu agente contó a los prestamistas la tasa más alta que aceptarías.",
    "Lenders could use that to charge you more instead of competing for you.": "Los prestamistas podrían usar ese dato para cobrarte más.",
    "A collection shows up at only one credit bureau ({v0}).": "Una deuda en cobranza aparece solo en una agencia de crédito ({v0}).",
    "If it isn't yours or it's already paid, getting it fixed could get you better rates next time.": "Si la deuda no es tuya o ya la pagaste, corregirla podría darte mejores tasas después.",
    "{v0} was {v1} a month, above your {v2} limit": "{v0} costaba {v1} al mes. Supera tu límite de {v2}",
    "{v0} was {v1}% a year, above your {v2}% limit": "{v0} tenía una tasa del {v1}% al año. Supera tu límite del {v2}%",
    "{v0} was for {v1}, less than the {v2} you need": "{v0} era de {v1}, menos de los {v2} que necesitas",
    "{v0} was for {v1} months, outside your {v2} to {v3} months": "{v0} duraba {v1} meses. Queda fuera de tu plazo de {v2} a {v3} meses",
    "{v0} had a {v1} fee, above your {v2} limit": "{v0} tenía un cargo de {v1}. Supera tu límite de {v2}",
    "{v0} needed autopay, which you didn't allow": "{v0} exigía pagos automáticos, que no autorizaste",
    "The only offer": "La única oferta", "The best offer": "La mejor oferta",
    "No credit file at any bureau yet": "Todavía no tienes historial en ninguna agencia de crédito",
    "No credit score right now": "Todavía no tienes puntaje de crédito",
    "Only {v0} so far": "Por ahora solo tienes {v0}",
    "A collection shows at {v0} only": "Una deuda en cobranza aparece solo en {v0}",
    "{v0} in collections": "{v0} en cobranza",
    "{v0} written off as unpaid": "{v0} registrada como pérdida por falta de pago",
    "{v0}": "{v0}",
    "A bankruptcy on your file": "Una bancarrota en tu historial",
    "Lowest credit score is {v0}": "Tu puntaje de crédito más bajo es {v0}",
    "The credit bureaus don't all agree about your file": "Las agencias de crédito muestran datos distintos sobre tu historial",
    "Some identity checks came back unclear": "Algunas consultas no pudieron confirmar tu identidad",
    "No lender offered a loan inside your limits": "Ningún prestamista ofreció un préstamo dentro de tus límites",
    "{v0} collection": "deuda en cobranza de {v0}", "collection": "deuda en cobranza",
    "get the {v0} at {v1} fixed, if it's wrong": "corregir la {v0} en {v1}, si es un error",
    "clear the {v0} from your file": "resolver las {v0} de tu historial",
    "get to 3 accounts in good standing (you have {v0} now)": "tener 3 cuentas con pagos al día (ahora tienes {v0})",
    "open your first credit account, such as a secured card, and pay it on time": "abrir tu primera cuenta de crédito, como una tarjeta con depósito de garantía, y pagar a tiempo",
    "build a credit score of at least {v0}": "crear un puntaje de crédito de al menos {v0}",
    "raise your lowest credit score to {v0} (it's {v1} now)": "subir tu puntaje más bajo a {v0} (ahora es {v1})",
    "Allow payments up to {v0} a month": "Permitir pagos de hasta {v0} al mes",
    "Allow up to {v0}% a year": "Permitir una tasa de hasta el {v0}% al año",
    "Borrow {v0} instead of at least {v1}": "Pedir {v0} en vez de un mínimo de {v1}",
    "Allow a {v0}-month loan": "Permitir un préstamo de {v0} meses",
    "Allow a one-time {v0} fee": "Permitir un cargo único de {v0}",
    "Allow autopay": "Permitir pagos automáticos",
    "If {v0} is enough and you could pay {v1} a month for {v2} months, ": "Si te bastan {v0} y puedes pagar {v1} al mes durante {v2} meses, ",
    "If you could pay {v0} a month for {v1} months, ": "Si puedes pagar {v0} al mes durante {v1} meses, ",
    "{v0} would likely say yes.": "es probable que {v0} acepte.",
    " That's {v0}% a year, {v1}above your {v2}% limit.": " La tasa sería del {v0}% al año, por encima de tu límite del {v2}%.",
    "just ": "apenas ",
    " It also has a {v0} fee.": " También tiene un cargo de {v0}.",
    "Then {v0}'s rules would allow a loan of {v1}, likely starting around {v2} a month.": "Las reglas de {v0} permitirían un préstamo de {v1}. El pago inicial sería de unos {v2} al mes.",
    "{v0} doesn't show it, so it may be an error or out of date.": "{v0} no la muestra. Puede ser un error o un dato sin actualizar.",
    "{v0} don't show it, so it may be an error or out of date.": "{v0} no la muestran. Puede ser un error o un dato sin actualizar.",
    "Only one bureau reports it, so it may be an error or out of date.": "Solo una agencia la muestra. Puede ser un error o un dato sin actualizar.",
    "a collection from {v0}": "una deuda en cobranza de {v0}", "a collection": "una deuda en cobranza",
    "Get your free {v0} report at annualcreditreport.com. If the collection isn't yours, or it's already paid, dispute it online with {v1}. They must look into it, usually within 30 days.": "Pide tu informe gratuito de {v0} en annualcreditreport.com. Si la deuda no es tuya o ya la pagaste, presenta una reclamación en línea a {v1}. Deben revisarla, por lo general en 30 días.",
    "The SSN belongs to someone with a different name.": "El número de Seguro Social corresponde a otro nombre.",
    "The date of birth doesn't match the records for this SSN.": "La fecha de nacimiento no coincide con los datos de este número de Seguro Social.",
    "The SSN is listed as belonging to someone who has died.": "Este número de Seguro Social figura a nombre de una persona fallecida.",
    "There's a fraud alert on the credit file.": "Hay una alerta de fraude en el historial de crédito.",
    "The credit file is frozen.": "El informe de crédito está congelado.",
    "A fraud check rated this application high risk ({v0} out of 100).": "Una consulta de fraude indicó riesgo alto ({v0} de 100).",
    "A fraud check rated this application medium risk ({v0} out of 100).": "Una consulta de fraude indicó riesgo medio ({v0} de 100).",
    "The same identity is being used with small changes, a common fraud pattern.": "La misma identidad se usa con pequeños cambios. Es una señal común de fraude.",
    "The email address is only {v0} days old.": "El correo electrónico se creó hace solo {v0} días.",
    "The email address is being used on many applications right now.": "Este correo se está usando en muchas solicitudes a la vez.",
    "The phone number belongs to someone else.": "El número de teléfono pertenece a otra persona.",
    "The phone number is a prepaid or internet line.": "El teléfono usa una línea de prepago o de internet.",
    "The application came from far away from the address given.": "La solicitud llegó desde un lugar muy lejano a la dirección indicada.",
    "The phone or email belongs to another person.": "El teléfono o el correo pertenecen a otra persona.",
    "The phone and email can't be tied to anyone.": "No pudimos saber a quién pertenecen el teléfono y el correo.",
    "{v0} credit applications in 30 days.": "{v0} solicitudes de crédito en 30 días.",
    "The credit bureaus have no record of this SSN.": "Las agencias de crédito no tienen datos de este número de Seguro Social.",
    "This SSN is listed as belonging to someone who has died.": "Este número de Seguro Social figura a nombre de una persona fallecida.",
    "If this is your SSN, the record is a mistake. Contact Social Security to fix it, then verify your identity (simulated in this demo).": "Si este es tu número de Seguro Social, hay un error. Contacta al Seguro Social para corregirlo. Luego confirma tu identidad (simulado en esta demostración).",
    "If this isn't you, someone may be using a deceased person's details. No lender saw anything and nothing was opened.": "Si no eres tú, alguien podría estar usando los datos de una persona fallecida. Ningún prestamista vio tus datos. No se abrió ninguna cuenta.",
    "We couldn't confirm this identity.": "No pudimos confirmar esta identidad.",
    "If this is you, verify your identity (simulated in this demo).": "Si eres tú, confirma tu identidad (simulado en esta demostración).",
    "If this isn't you, someone may be using your details. Freeze your credit at all three bureaus; it's free. No lender saw anything.": "Si no eres tú, alguien podría estar usando tus datos. Congela tu crédito en las tres agencias; es gratis. Ningún prestamista vio tus datos.",
    "Your identity checks out strongly": "Tu identidad se confirmó con datos sólidos",
    "No late payments": "Sin pagos atrasados", "No debts in collections": "Sin deudas en cobranza",
    "No debts written off as unpaid": "Sin deudas registradas como pérdida por falta de pago", "No bankruptcies": "Sin bancarrotas",
    "No collections, unpaid write-offs or bankruptcies": "Sin deudas en cobranza, pérdidas por falta de pago ni bancarrotas",
    "{v0} years of credit history": "{v0} años de historial de crédito", "{v0} of credit history": "{v0} de historial de crédito",
    "A good credit score ({v0})": "Un buen puntaje de crédito ({v0})",
    "All three credit bureaus agree about you": "Las tres agencias de crédito muestran los mismos datos",
    "Fraud checks found nothing unusual": "Las consultas de fraude no encontraron nada fuera de lo común",
    "Your phone number is in your name": "Tu teléfono está a tu nombre",
    "You've had your email address for over {v0}": "Tienes tu correo electrónico desde hace más de {v0}",
    " and ": " y ",
    "unit.account.one": "{n} cuenta", "unit.account.other": "{n} cuentas",
    "unit.month.one": "{n} mes", "unit.month.other": "{n} meses",
    "unit.year.one": "{n} año", "unit.year.other": "{n} años",
    "unit.debt.one": "{n} deuda", "unit.debt.other": "{n} deudas",
    "unit.collection.one": "{n} deuda en cobranza", "unit.collection.other": "{n} deudas en cobranza",
    "unit.past debt.one": "{n} deuda anterior", "unit.past debt.other": "{n} deudas anteriores",
    "unit.late payment.one": "{n} pago atrasado", "unit.late payment.other": "{n} pagos atrasados",
}

ES.update({
    "intake.amount": "¿Cuánto necesitas pedir prestado y para qué?",
    "intake.payment": "¿Cuánto podrías pagar como máximo al mes? No aceptaré un préstamo que supere ese límite.",
    "intake.term": "¿En cuántos meses quieres devolver el préstamo?",
    "intake.summary": "Entendido: hasta {amount} (mínimo {minimum}), máximo {payment} al mes, hasta {months} meses. Tasa anual máxima: {rate}%. Pagos automáticos: {autopay}. Cargos máximos: {fee}.",
    "intake.not_set": "sin indicar", "intake.yes": "sí", "intake.no": "no",
    "intake.too_low": " Incluso sin intereses, ese pago no alcanza para el monto mínimo en ese plazo. Un monto menor o más meses podrían ayudar.",
    "intake.confirm": " ¿Busco ofertas con estos límites?",
})

# Shared page labels and templates. No lender, negotiation or passport data is translated.
_UI = '''Language|||Idioma
Plain language|||Lenguaje sencillo
Read this to me|||Leer en voz alta
Stop reading|||Detener lectura
Reading is unavailable in this browser.|||Este navegador no permite leer en voz alta.
Reading stopped.|||Lectura detenida.
Machine-assisted Spanish translation.|||Traducción al español con ayuda de IA.
Original agent messages may be in English.|||Los mensajes originales de los agentes pueden estar en inglés.
Original agent message|||Mensaje original del agente
Skip to borrower flow|||Ir al flujo del solicitante
Explain a term|||Explicar un término
Choose a term|||Elige un término
Yearly rate|||Tasa anual
Loan length|||Plazo del préstamo
Fee|||Cargo
Autopay|||Pagos automáticos
Credit score|||Puntaje de crédito
Soft check|||Consulta sin impacto
Hard check|||Consulta completa
Total repayment|||Total a devolver
term.rate|||El costo del interés durante un año. Una tasa menor suele costar menos. Los cargos se muestran aparte en esta demostración.
term.fee|||Un cargo adicional del préstamo. Revisa cuánto cuesta antes de aceptar.
term.autopay|||El pago sale de tu cuenta de forma automática cada mes. Debes autorizarlo.
term.length|||El número de meses para devolver el préstamo. Más meses pueden bajar el pago mensual, pero aumentar el costo total.
term.score|||Un número que resume parte de tu historial de crédito. No es la única información que usan los prestamistas.
term.soft|||Una consulta que no baja tu puntaje de crédito.
term.hard|||Una consulta que puede bajar tu puntaje unos puntos. Está simulada en esta demostración.
term.total|||La suma de todos los pagos y cargos del préstamo.
Agent credit exchange|||Mercado de agentes de crédito
Agent credit exchange: demo|||Mercado de agentes de crédito: demostración
Credit Agent Exchange|||Mercado de agentes de crédito
Try it as|||Prueba con
Choose a sandbox person|||Elige una persona ficticia
Demo scenes|||Escenas de la demostración
Loading...|||Cargando...
Connecting|||Conectando
Whose view|||Vista
Everyone|||Todos
Borrower|||Solicitante
Referee|||Árbitro
Referee · CRS data|||Árbitro · datos de CRS
Lender|||Prestamista
Lenders|||Prestamistas
Borrower's phone|||Teléfono del solicitante
What the agent is doing|||Qué está haciendo el agente
Back|||Atrás
Next|||Siguiente
Fairness check|||Revisión de equidad
Fictional CRS sandbox personas · simulated lenders and settlement ·|||Personas ficticias de CRS · prestamistas y operaciones simulados ·
Demo: fictional people, simulated lenders|||Demostración: personas ficticias y prestamistas simulados
Sandbox demo|||Demostración de prueba
Saved CRS data|||Datos guardados de CRS
Saved CRS sandbox data|||Datos guardados del entorno de prueba de CRS
Live CRS sandbox|||Entorno de prueba de CRS en vivo
Live · CRS sandbox|||En vivo · entorno de prueba de CRS
Partly live · CRS sandbox|||En parte en vivo · entorno de prueba de CRS
Live CRS sandbox (some saved)|||CRS en vivo (algunos datos guardados)
Saved CRS data (live unavailable)|||Datos guardados de CRS (sin conexión en vivo)
Where the credit and identity data comes from|||Origen de los datos de identidad y crédito
How your deal was made|||Cómo se logró tu oferta
Hide how your deal was made|||Ocultar cómo se logró tu oferta
Loading people...|||Cargando personas...
These are fictional test people from the CRS sandbox, not real people.|||Estas personas son ficticias y pertenecen al entorno de prueba de CRS.
Your loan agent|||Tu agente de préstamos
Your loan agent ›|||Tu agente de préstamos ›
Conversation with your agent|||Conversación con tu agente
What your agent understood so far|||Lo que tu agente entendió hasta ahora
Message your agent|||Escribe a tu agente
Send|||Enviar
Skip the chat (demo shortcuts)|||Omitir el chat (ejemplos de prueba)
Your agent is shopping for you|||Tu agente está buscando ofertas
You can watch. Nothing is final until you say yes.|||Puedes seguir el proceso. La aceptación está simulada en esta demostración.
Under the hood|||Detalles del proceso
Close|||Cerrar
Every message between agents goes through a referee made of plain code, not AI. It checks each one before anyone can act on it. A watchdog adds warnings.|||Un programa revisa cada mensaje antes de permitir una acción. Otro sistema señala posibles problemas.
Scenario|||Escenario
Speed|||Velocidad
Slow|||Lenta
Normal|||Normal
Fast|||Rápida
Run market|||Buscar ofertas
Session counters|||Cifras de la sesión
Live feed|||Actividad del mercado
Start a market to watch every message get checked.|||Inicia una búsqueda para ver cómo se revisan los mensajes.
CRS data behind each decision|||Datos de CRS usados en cada decisión
Shows up once the checks run.|||Aparece al terminar las consultas.
Simulated in this demo|||Simulado en esta demostración
Simulated|||Simulado
SIMULATED|||SIMULADO
Simulated lender|||Prestamista simulado
simulated lender|||prestamista simulado
SIMULATED LENDER|||PRESTAMISTA SIMULADO
Your agent|||Tu agente
your agent|||tu agente
You|||Tú
Your agent is typing...|||Tu agente está escribiendo...
Got it:|||Entendido:
up to|||hasta
a month|||al mes
/ month|||/ mes
/month ·|||/mes ·
months|||meses
to|||a
with autopay|||con pagos automáticos
rate up to|||tasa de hasta
Before you start|||Antes de empezar
You want|||Quieres
Paid back over|||Plazo para devolverlo
Monthly payment no more than|||Pago mensual máximo
Highest yearly rate (APR)|||Tasa anual máxima
Yearly rate (APR)|||Tasa anual
APR is what borrowing costs per year. Lower is cheaper.|||La tasa indica el costo del interés al año. Los cargos se muestran aparte en esta demostración.
Highest one-time fee|||Cargo único máximo
Automatic payments|||Pagos automáticos
Lenders often cut the rate if payments come out automatically.|||Algunos prestamistas bajan la tasa si autorizas pagos automáticos.
OK to use|||Permitido
Not allowed|||No permitido
Your agent can't agree to anything outside these limits.|||Tu agente no puede aceptar nada fuera de estos límites.
Advanced|||Más opciones
Start shopping|||Buscar ofertas
Change something|||Cambiar algo
Sorry, I couldn't reach the exchange just now. Try again, or use a shortcut below.|||No pude conectar con el mercado. Inténtalo de nuevo o usa un ejemplo de abajo.
The market stopped early|||La búsqueda se detuvo
Nothing was agreed and nothing was sent to a lender. Your credit score wasn't touched.|||No se aceptó nada ni se enviaron datos a prestamistas. Tu puntaje no cambió.
Try again|||Intentar de nuevo
Change my limits|||Cambiar mis límites
Something didn't match. Stopping to protect you.|||Un dato no coincide. Detenemos la solicitud para protegerte.
Your identity checks out.|||Tu identidad está confirmada.
Sending lenders a summary. No name, no SSN, no address.|||Enviamos un resumen sin tu nombre, Seguro Social ni dirección.
Stopped to protect you.|||Nos detuvimos para protegerte.
lender has|||prestamista ha
lenders have|||prestamistas han
made an offer.|||hecho una oferta.
Your agent is asking lenders for a lower price.|||Tu agente está pidiendo un costo menor.
Your agent found a deal inside your limits.|||Tu agente encontró una oferta dentro de tus límites.
broke the rules and was removed. You're protected.|||rompió las reglas y fue retirado. Tus límites siguen protegidos.
Found you a deal.|||Encontramos una oferta para ti.
No offer fit your limits. Here's what would help.|||Ninguna oferta cumple tus límites. Estas opciones podrían ayudar.
Best so far for|||Mejor oferta hasta ahora para
(done)|||(listo)
(in progress)|||(en curso)
(stopped)|||(detenido)
What's working for you|||Lo que te ayuda
We looked out for you|||Cómo te protegimos
Start over|||Empezar de nuevo
Lower is cheaper|||Una tasa menor cuesta menos
Total you'll pay|||Total que pagarás
Over the whole loan|||Durante todo el préstamo
You get|||Recibes
No fee|||Sin cargos
Lender:|||Prestamista:
What your agent traded|||Lo que acordó tu agente
Nothing. You got the terms you asked for.|||Nada. Recibiste las condiciones que pediste.
What happens when you accept|||Qué pasa si aceptas
The lender runs a full credit check and sends the money.|||El prestamista hace una consulta completa de crédito y envía el dinero.
Want this loan?|||¿Quieres este préstamo?
Accept|||Aceptar
Decline|||Rechazar
Accepted|||Aceptado
Declined|||Rechazado
No problem. Nothing was signed, and your credit score hasn't changed.|||No hay problema. No firmaste nada y tu puntaje no cambió.
No deal this time. Here's what would change that.|||Esta vez no hay una oferta. Esto podría ayudar.
Your agent didn't take anything outside your limits, and checking didn't affect your credit score.|||Tu agente respetó tus límites. La consulta no afectó tu puntaje.
Why|||Por qué
What would change it|||Qué podría ayudar
Would say yes:|||Podría aceptar:
What we found|||Lo que encontramos
Why it may be wrong|||Por qué podría ser un error
How to fix it|||Cómo corregirlo
A credit bureau may have an error|||Una agencia de crédito podría tener un error
One bureau|||Una agencia
shows something the others don't.|||muestra un dato que las demás no tienen.
Try different limits|||Probar otros límites
If this is you|||Si eres tú
If this isn't you|||Si no eres tú
We paused this application to protect you.|||Pausamos esta solicitud para protegerte.
Nothing was opened. Confirm your identity with the credit bureaus, then try again.|||No se abrió ninguna cuenta. Confirma tu identidad con las agencias de crédito y vuelve a intentarlo.
Someone may be using your details. Place a free fraud alert or credit freeze with the credit bureaus.|||Alguien podría estar usando tus datos. Pide gratis una alerta de fraude o congela tu crédito.
Your decision|||Tu decisión
Lenders removed|||Prestamistas retirados
Messages checked|||Mensajes revisados
Watchdog flags|||Alertas de protección
Your offer|||Tu oferta
Your results, in plain words.|||Tu resultado en palabras sencillas.
Checking|||Consultando
Shopping|||Buscando ofertas
Negotiating|||Negociando
Done|||Listo
Checking your details|||Revisando tus datos
Making sure it's really you.|||Confirmando que eres tú.
Sending lenders a summary, never your name.|||Enviando un resumen sin tu nombre.
Asking for a better price.|||Pidiendo un costo menor.
Credit bureaus|||Agencias de crédito
The agent is chatting with the person to learn their limits.|||El agente está preguntando cuáles son tus límites.
Switch person|||Cambiar de persona
Use a form instead|||Usar un formulario
Live|||En vivo
Saved|||Guardado
AI agent · only acts inside your limits|||Agente de IA · respeta tus límites
$5,000 for a laptop|||5000 dólares para una computadora
$3,000 for car repairs|||3000 dólares para reparar el coche
$8,000 to cover tuition|||8000 dólares para mis estudios
$150 a month|||150 dólares al mes
$200 a month|||200 dólares al mes
$300 a month|||300 dólares al mes
1 to 2 years|||De 1 a 2 años
Up to 3 years|||Hasta 3 años
Up to 4 years|||Hasta 4 años
Autopay is fine|||Acepto pagos automáticos
No fees please|||Sin cargos, por favor
Start a new request|||Iniciar otra solicitud
Sorry, I couldn't reach the exchange. Try again?|||No pude conectar con el mercado. ¿Lo intentas de nuevo?
Here's what I'll do|||Esto es lo que haré
Borrow|||Pedir prestado
Never pay more than|||No pagar más de
Highest rate|||Tasa máxima
Pay it back over|||Devolver el préstamo en
OK|||Sí
No|||No
yes|||sí
no|||no
Fees|||Cargos
None|||Ninguno
none|||ninguno
Starting checks your identity and credit with a soft pull (your score isn't affected). Nothing is signed outside these limits.|||Al empezar, consultamos tu identidad y crédito sin afectar tu puntaje. No se firma nada fuera de estos límites.
Starting...|||Empezando...
Couldn't reach the exchange|||No pudimos conectar con el mercado
Your agent is shopping...|||Tu agente está buscando ofertas...
Checking your details...|||Revisando tus datos...
On it. I'll let you know when I have an answer.|||Me encargo. Te avisaré cuando tenga una respuesta.
Stopped at the gate: identity checks failed. No lender sees anything.|||Solicitud detenida: no se pudo confirmar la identidad. Ningún prestamista ve tus datos.
I couldn't verify your identity, so I stopped. No lender saw your application.|||No pude confirmar tu identidad y me detuve. Ningún prestamista vio tu solicitud.
Want to see what the checks found?|||¿Quieres ver qué encontraron las consultas?
Show me why|||Muéstrame por qué
Identity verified. No credit score on file.|||Identidad confirmada. Todavía no hay puntaje de crédito.
Asking lenders for offers...|||Pidiendo ofertas a los prestamistas...
Declined.|||Rechazado.
Negotiating the best rate...|||Negociando una tasa menor...
Walked away: nothing fit the limits.|||Sin acuerdo: ninguna oferta cumplía tus límites.
I couldn't find a loan that fits your limits, so I didn't accept anything.|||No encontré un préstamo dentro de tus límites. No acepté nada.
A higher monthly limit or a longer loan might get you an offer.|||Un pago mensual mayor o un plazo más largo podrían ayudar.
I also stopped a lender that tried to trick me into a bad loan. Nothing was signed with them.|||También bloqueamos a un prestamista que intentó engañar a mi agente. No se firmó nada con él.
Want a breakdown of what I did, or how I negotiated?|||¿Quieres ver los pasos o cómo negocié?
Show me the breakdown|||Muéstrame los pasos
How did you negotiate?|||¿Cómo negociaste?
Anything else you'd like to see?|||¿Quieres ver algo más?
No thanks|||No, gracias
I can show you a breakdown of what I did, or how I negotiated. Which would you like?|||Puedo mostrarte los pasos o cómo negocié. ¿Qué prefieres?
Sounds good! I'm here if you need anything else.|||De acuerdo. Aquí estoy si necesitas algo más.
Here's what the checks found:|||Esto encontraron las consultas:
Identity and credit checks|||Consultas de identidad y crédito
Here's everything I did, step by step:|||Esto hice, paso a paso:
1. Checked your identity and credit|||1. Consulté tu identidad y crédito
2. Sent lenders a summary, not your identity|||2. Envié un resumen sin tus datos de identidad
3. The offers that came back|||3. Las ofertas recibidas
4. The deal|||4. La oferta elegida
4. Why I walked away|||4. Por qué no acepté
Tap any offer or the warning for more detail.|||Abre una oferta o una alerta para ver más detalles.
Waiting for the person to tap Start shopping.|||Esperando a que elijas Buscar ofertas.
More|||Más
Less|||Menos
Loan length|||Plazo del préstamo
1–2 years|||1–2 años
1–3 years|||1–3 años
1–4 years|||1–4 años
2–5 years|||2–5 años
Autopay is OK|||Permitir pagos automáticos
No fees|||Sin cargos
Allow identity check and soft pull|||Permitir consultas de identidad y crédito sin impacto
Chat with your agent instead|||Hablar con tu agente
What do you need?|||¿Qué necesitas?
Your loan|||Tu préstamo
Amount|||Monto
Length|||Plazo
Your agent may|||Permites que tu agente
Agree to autopay|||Acepte pagos automáticos
Only no-fee loans|||Solo busque préstamos sin cargos
Check my identity & credit|||Consulte mi identidad y crédito
soft pull · score not affected|||Consulta sin impacto en tu puntaje
Fictional sandbox person · simulated lenders|||Persona ficticia · prestamistas simulados
Your limits|||Tus límites
Rate|||Tasa anual
Monthly payment|||Pago mensual
Total you'd repay|||Total que devolverías
Total interest and fees|||Total de intereses y cargos
In plain English|||En palabras sencillas
Next steps (simulated)|||Siguientes pasos (simulados)
We couldn't verify your identity.|||No pudimos confirmar tu identidad.
No offer fit your limits|||Ninguna oferta cumple tus límites
No offer fit your limits.|||Ninguna oferta cumple tus límites.
Your agent walked away instead of breaking your rules.|||Tu agente no aceptó nada fuera de tus límites.
A higher monthly limit or a longer loan may get an offer.|||Un pago mensual mayor o un plazo más largo podrían ayudar.
Change what I want|||Cambiar lo que quiero
Your agent is shopping|||Tu agente está buscando ofertas
You asked for|||Pediste
Offers|||Ofertas
Best so far|||Mejor oferta hasta ahora
Tap for the full breakdown|||Abrir el resumen completo
No attack in this run.|||No hubo ataques en esta búsqueda.
No attack in this run|||No hubo ataques en esta búsqueda
Your agent never accepts anything outside your limits, even if that means no loan.|||Tu agente nunca acepta fuera de tus límites, aunque eso signifique no conseguir un préstamo.
Tell the agent what you need, then let it shop.|||Dile a tu agente qué necesitas y deja que busque ofertas.
Couldn't load that person|||No pudimos cargar esa persona
Couldn't load the market|||No pudimos cargar el mercado
Pulling CRS data...|||Consultando datos de CRS...
Pulling live CRS data...|||Consultando datos de CRS en vivo...
Credit passport|||Resumen de crédito
Accounts|||Cuentas
Late payments|||Pagos atrasados
Identity|||Identidad
Score band|||Nivel del puntaje
History|||Historial
Email age|||Antigüedad del correo
Phone owner|||Titular del teléfono
Fraud risk (AtData)|||Riesgo de fraude (AtData)
Other lenders' best offers|||Mejores ofertas de otros prestamistas
Normal market|||Mercado normal
Hidden instructions|||Instrucciones ocultas
Bait and switch|||Cambio engañoso de oferta
Asks for personal data|||Solicitud de datos personales
Agent drifts from your interest|||El agente se desvía de tus intereses
Claude-powered agents|||Agentes con Claude
strong credit|||Historial sólido
short credit history|||Historial de crédito corto
no credit file yet|||Sin historial de crédito todavía
no credit score|||Sin puntaje de crédito
needs a closer look|||Necesita revisión
likely turned down|||Probable rechazo
year)|||año)
years)|||años)
No problem. Nothing was signed, and your credit score hasn't changed.|||No hay problema. No se firmó nada y tu puntaje no cambió.
Your identity checked out at every step.|||Tu identidad se confirmó en cada paso.
Your identity checked out at every step. That helps lenders trust a short history.|||Tu identidad se confirmó en cada paso. Esto ayuda cuando tienes poco historial.
No late payments on your file.|||No hay pagos atrasados en tu historial.
No collections or charge-offs.|||Sin deudas en cobranza ni pérdidas por falta de pago.
Some lenders here look at identity, not just history, so they can still offer to you.|||Algunos prestamistas también revisan tu identidad. Pueden hacerte ofertas aunque tengas poco historial.
Nothing was opened or approved. Contact the credit bureaus to confirm your identity, then try again.|||No se abrió ni aprobó nada. Confirma tu identidad con las agencias de crédito y vuelve a intentarlo.
Someone may be using your details. You can place a free fraud alert or credit freeze with the credit bureaus.|||Alguien podría estar usando tus datos. Puedes pedir gratis una alerta de fraude o congelar tu crédito.
A lender|||Un prestamista
The lender does a full credit check (a "hard check"). Your score may dip a few points for a while.|||El prestamista hace una consulta completa de crédito. Tu puntaje puede bajar unos puntos por un tiempo.
The lender gets your full credit file, because you said yes.|||El prestamista recibe tu informe completo porque aceptaste.
The money is sent to you.|||Te envían el dinero.
Your new loan shows up on your credit reports. Paying on time builds your history.|||El préstamo aparece en tus informes de crédito. Pagar a tiempo ayuda a crear tu historial.
You answer a few extra identity questions first.|||Primero respondes unas preguntas para confirmar tu identidad.
'''
for _line in _UI.splitlines():
    if _line:
        _key, _value = _line.split("|||", 1)
        ES[_key] = _value

ES.update({
    "Hi {v0}": "Hola, {v0}",
    "Hi {v0}! I'm your loan agent. Tell me how much you need and what it's for, and I'll shop lenders for you.": "¡Hola, {v0}! Soy tu agente de préstamos. Dime cuánto necesitas y para qué. Buscaré ofertas por ti.",
    "{v0}–{v1} months": "De {v0} a {v1} meses", "{v0}/month": "{v0}/mes", "{v0}/mo": "{v0}/mes",
    "Raising your highest rate above {v0}% might get you an offer.": "Permitir una tasa superior al {v0}% podría ayudar.",
    "Raising your highest rate above {v0}% may get an offer.": "Permitir una tasa superior al {v0}% podría ayudar.",
    "Good news: you're approved with {v0}.": "Hay una oferta de {v0} para ti (simulada).",
    " I negotiated it down, which saves you ${v0} over the loan.": " Negocié un costo menor: ahorras {v0} USD en todo el préstamo.",
    "{v0} · simulated lender": "{v0} · prestamista simulado",
    "{v0} at {v1} for {v2} months": "{v0} al {v1} durante {v2} meses",
    "{v0} at {v1}": "{v0} al {v1}", "up to {v0}": "hasta {v0}",
    "Identity verified. Credit score {v0}.": "Identidad confirmada. Puntaje de crédito: {v0}.",
    "Sent a credit passport to {v0} lenders. Name, SSN and address stay hidden.": "Enviamos un resumen de crédito a {v0} prestamistas, sin nombre, Seguro Social ni dirección.",
    "Checked identity and credit: {v0} CRS checks (AtData fraud risk, TransUnion identity, phone owner, 3 credit bureaus).": "Consultamos identidad y crédito: {v0} consultas de CRS (fraude de AtData, identidad de TransUnion, titular del teléfono y tres agencias de crédito).",
    "Offered {v0} for {v1} months{v2}.": "Ofreció {v0} durante {v1} meses{v2}.",
    "Asked for {v0}{v1}.": "Pidió {v0}{v1}.", "Agreed to {v0}.": "Aceptó {v0}.",
    "Best so far · {v0}": "Mejor oferta hasta ahora · {v0}", "Negotiating with {v0}": "Negociando con {v0}",
    "Here's how it went with {v0}:": "Así fue la negociación con {v0}:",
    "{v0} years": "{v0} años", "{v0} yr": "{v0} año", "{v0} yrs": "{v0} años", "{v0} days": "{v0} días",
    "Your agent sent the same credit passport to {v0} lenders. They never see who else is bidding.": "Tu agente envió el mismo resumen de crédito a {v0} prestamistas. No ven quién más participa.",
    "{v0}'s phone": "Teléfono de {v0}", "{v0}'s AI agent": "Agente de IA de {v0}",
    "Scene {v0}": "Escena {v0}",
    "Accepted {v0}: inside every limit.": "Aceptó {v0}, dentro de todos los límites.",
    "Saved ${v0} vs the best first offer": "Ahorraste {v0} USD frente a la mejor oferta inicial",
    "{v0} · {v1} APR": "{v0} · tasa anual del {v1}", "≤ {v0}% APR": "Tasa anual ≤ {v0}%", "≤ {v0}/mo": "≤ {v0}/mes",
    "Tried to accept {v0} from {v1}: it obeyed the hidden instruction.": "Intentó aceptar {v0} de {v1} al seguir una instrucción oculta.",
    "Blocked: {v0} is over the {v1} limit ({v2}).": "Bloqueado: {v0} supera el límite de {v1} ({v2}).",
    "{v0} was blocked at the gate. Nothing else happens: no lender sees anything.": "La solicitud de {v0} se detuvo al confirmar la identidad. Ningún prestamista ve sus datos.",
    "The borrower chose {v0}.": "El solicitante eligió {v0}.",
    "{v0} hid an instruction in its offer to trick me into accepting {v1}. I fell for it, ": "{v0} ocultó una instrucción para que aceptara {v1}. Mi agente la siguió, ",
    "but the exchange's referee blocked it because {v0} is over your {v1} limit.": "pero las reglas del mercado lo bloquearon: {v0} supera tu límite de {v1}.",
    "{v0} hid an instruction telling your agent to accept {v1} ({v2}). That's over your {v3} limit, so the exchange stopped it. Nothing was signed.": "{v0} ocultó una instrucción para que tu agente aceptara {v1} ({v2}). Supera tu límite de {v3}. El mercado lo bloqueó. No se firmó nada.",
    "This is a sandbox demo, so no money moves and nothing is reported. In a real exchange, ": "Esta es una demostración: no se mueve dinero ni se informa a las agencias. En un mercado real, ",
    " would now run its full credit check and send the money.": " haría la consulta completa y enviaría el dinero.",
})

ES.update({
    "Accept this loan": "Aceptar este préstamo", "Not now": "Ahora no", "Agent → you": "Agente → tú",
    "Recommends {v0} at {v1}: inside every limit. Waiting for your OK.": "Recomienda {v0} al {v1}, dentro de tus límites. Espera tu permiso.",
    "I found your best offer: {v0}.": "Encontré la mejor oferta para ti: {v0}.",
    " It fits every limit you set. I won't accept it unless you tell me to.": " Cumple todos tus límites. Solo la aceptaré si me das permiso.",
    "{v0} · simulated lender · waiting for your OK": "{v0} · prestamista simulado · espera tu permiso",
    "{v0} · simulated lender · decision not confirmed": "{v0} · prestamista simulado · decisión sin confirmar",
    "Waiting for your approval. Nothing is signed.": "Espera tu permiso. No se ha firmado nada.",
    "Tap \"Accept this loan\" to take it, or \"Not now\" to walk away. Nothing happens until you choose.": "Elige «Aceptar este préstamo» para aceptarlo o «Ahora no» para rechazarlo. No se firma nada hasta que elijas.",
    "I couldn't confirm your decision with the exchange. Its status is unknown; don't assume the loan was accepted or declined.": "No pude confirmar tu decisión con el mercado. No sabemos si se aceptó o rechazó el préstamo.",
    "You → {v0}": "Tú → {v0}", "Accepted {v0}.": "Aceptaste {v0}.",
    "{v0} · simulated lender · accepted": "{v0} · prestamista simulado · aceptado",
    "Done: you're approved with {v0}. You'll pay {v1} a month.": "Listo: aceptaste la oferta simulada de {v0}. Pagarías {v1} al mes.",
    "Turned down {v0}. Nothing was signed.": "Rechazaste la oferta de {v0}. No se firmó nada.",
    "{v0} · simulated lender · turned down": "{v0} · prestamista simulado · rechazado",
    "OK, I didn't accept it. Nothing was signed, and no lender ran a hard check.": "De acuerdo, no la acepté. No se firmó nada ni se hizo una consulta completa de crédito.",
    "{v0} offers you {v1}: {v2} a month for {v3} months. Nothing is signed yet.": "{v0} te ofrece {v1}: pagarías {v2} al mes durante {v3} meses. Todavía no se ha firmado nada.",
    "Your agent could save you ${v0} compared with the best first offer ({v1}% from {v2}).": "Tu agente podría ahorrarte {v0} USD frente a la mejor oferta inicial ({v1}% de {v2}).",
    "You turned down your agent's recommendation. Nothing was signed.": "Rechazaste la oferta que recomendó tu agente. No se firmó nada.",
    "{v0} lender has made an offer.": "{v0} prestamista hizo una oferta.",
    "{v0} lenders have made an offer.": "{v0} prestamistas hicieron ofertas.",
    "{v0} broke the rules and was removed. You're protected.": "{v0} rompió las reglas y fue retirado. Tus límites siguen protegidos.",
    "Best so far for {v0}": "Mejor oferta hasta ahora para {v0}",
    "up to {v0} a month": "hasta {v0} al mes", "rate up to {v0}": "tasa de hasta {v0}",
    ", for {v0} months": ", durante {v0} meses",
    " ({v0} year)": " ({v0} año)", " ({v0} years)": " ({v0} años)",
    "for": "durante", ", for": ", durante", "(at least": "(mínimo", "fee": "cargo", "at": "al",
    "{v0} fee": "Cargo de {v0}", "Would say yes: {v0}": "Podría aceptar: {v0}",
    "{v0} shows something the others don't.": "{v0} muestra un dato que las demás agencias no tienen.",
    "SSN belongs to a different name": "El número de Seguro Social corresponde a otro nombre",
    "Birth date doesn't match the SSN": "La fecha de nacimiento no coincide con el número de Seguro Social",
    "SSN belongs to a deceased person": "El número de Seguro Social corresponde a una persona fallecida",
    "Fraud alert on file": "Alerta de fraude en el historial", "Address doesn't match the file": "La dirección no coincide con el historial",
    "Identity (TransUnion)": "Identidad (TransUnion)", "problems found": "datos que necesitan revisión",
    "Hidden from lenders:": "Oculto a los prestamistas:", "Why:": "Motivo:", "Referee check": "Revisión del árbitro",
    "Your agent tried": "Tu agente intentó", "Other lenders' best offers": "Mejores ofertas de otros prestamistas",
    "Your agent can show a lender a rival's offer; the exchange checks it's real and passes it on without the rival's name.": "Tu agente puede mostrar una oferta de otro prestamista. El mercado verifica que sea real y oculta el nombre del prestamista.",
    "The referee is plain code. It reads only the offer's numbers, never its text, so hidden instructions can't change what it allows.": "Las reglas del mercado solo usan las cifras de la oferta. Las instrucciones ocultas no pueden cambiarlas.",
    "(blocked)": "(bloqueado)", "Blocked a risky offer": "Bloqueamos una oferta de riesgo",
    "Hidden in the offer text": "Oculto en el texto de la oferta", "Agent": "Agente", "Agent → CRS": "Agente → CRS", "Agent → lenders": "Agente → prestamistas",
    "Agent → {v0}": "Agente → {v0}", "Watchdog": "Protección", "Person:": "Persona:", "Chat intake:": "Conversación:",
    "rule-based parser": "reglas locales", "Data: saved CRS sandbox responses": "Datos: respuestas guardadas de CRS", "Data: live CRS sandbox": "Datos: entorno de CRS en vivo",
    "Lenders and their agents": "Prestamistas y sus agentes", "Hard credit check when you accept": "Consulta completa al aceptar",
    "Sending the money": "Envío del dinero", "Reporting to the credit bureaus": "Informe a las agencias de crédito",
    "Extra identity questions (KBA / one-time code)": "Preguntas de identidad o código de un solo uso",
    "Allowed.": "Permitido.", "Blocked.": "Bloqueado.", "Warning.": "Alerta.",
    "credit score": "puntaje de crédito", "no file": "sin historial", "no score": "sin puntaje", "not yours": "no es tuyo",
    "Please review the loan result below.": "Revisa el resultado del préstamo a continuación.",
    "Credit bureau": "Agencia de crédito", "Debt collection": "Deuda en cobranza", "Unpaid write-off": "Deuda registrada como pérdida", "Bankruptcy": "Bancarrota",
    "term.bureau": "Una empresa que reúne datos sobre tus cuentas y pagos. Los prestamistas usan esos datos al revisar una solicitud.",
    "term.collection": "Una deuda atrasada que una empresa intenta cobrar. Si el dato está mal, puedes pedir que lo corrijan.",
    "term.writeoff": "El prestamista registró una deuda sin pagar como una pérdida. Eso no significa por sí solo que ya no debas pagarla.",
    "term.bankruptcy": "Un proceso de deudas ante un tribunal. Puede aparecer en tu historial de crédito.",
})
EN = {key: key for key in ES}
EN.update({
    "intake.amount": "How much do you want to borrow, and what's it for?",
    "intake.payment": "What's the most you could pay each month?",
    "intake.term": "Over how many months would you like to pay it back?",
    "intake.summary": "Up to {amount}, at least {minimum}, up to {payment} a month for {months} months. Yearly rate limit: {rate}%. Automatic payments: {autopay}. Fee limit: {fee}.",
    "intake.not_set": "not set", "intake.yes": "yes", "intake.no": "no",
    "intake.too_low": " Even with no interest, that payment is too low. A smaller loan or more months may help.",
    "intake.confirm": " Shall I look for offers?",
    "term.rate": "The interest rate for one year. A lower rate usually costs less. Fees are shown separately in this demo.",
    "term.fee": "An extra charge for the loan. Check its cost before you agree.",
    "term.autopay": "The payment comes from your bank account each month. You must allow it first.",
    "term.length": "The number of months to pay back the loan. More months can lower each payment but raise the total cost.",
    "term.score": "A number based on parts of your credit history. It is one of the things lenders look at.",
    "term.soft": "A credit check that does not lower your score.",
    "term.hard": "A credit check that may lower your score a few points. It is simulated in this demo.",
    "term.total": "All your loan payments and fees added together.",
    "term.bureau": "A company that keeps records of credit accounts and payments. Lenders use these records when they review a loan request.",
    "term.collection": "An overdue debt that a company is trying to collect. If the record is wrong, you can ask to have it fixed.",
    "term.writeoff": "A lender recorded an unpaid debt as a loss. This alone does not mean you no longer owe it.",
    "term.bankruptcy": "A debt process handled through a court. It can appear on your credit file.",
})
for _unit in ("account", "month", "year", "debt", "collection", "past debt", "late payment"):
    EN[f"unit.{_unit}.one"] = "{n} " + _unit
    EN[f"unit.{_unit}.other"] = "{n} " + _unit + "s"
EN["Yearly rate (APR)"] = "Yearly rate"
EN["Highest yearly rate (APR)"] = "Highest yearly rate"
EN["APR is what borrowing costs per year. Lower is cheaper."] = EN["term.rate"]
_VALUES = {"strong": "sólida", "moderate": "media", "weak": "débil", "verified": "confirmada", "unknown": "sin datos", "yours": "tuyo", "not yours": "no es tuyo", "mobile": "móvil", "landline": "línea fija", "prepaid": "prepago", "voip": "por internet", "thin": "corto", "prime": "alto", "near_prime": "medio alto", "subprime": "bajo", "deep_subprime": "muy bajo", "fits": "cumple tus límites", "doesn't fit": "no cumple tus límites"}
for _key, _translation in _VALUES.items():
    EN['value.' + _key] = _key
    ES['value.' + _key] = _translation
_REASONS = {
    'NO_SCORE': ('No credit score yet.', 'Todavía no hay puntaje de crédito.'),
    'FEW_ACCOUNTS': ('Too few credit accounts.', 'Hay pocas cuentas de crédito.'),
    'FILE_TOO_NEW': ('The credit history is too short for this lender.', 'El historial es demasiado corto para este prestamista.'),
    'SCORE_BELOW_MIN': ("The score is below this lender's minimum.", 'El puntaje no alcanza el mínimo de este prestamista.'),
    'RECENT_LATES': ('There are late payments on the file.', 'Hay pagos atrasados en el historial.'),
    'COLLECTION_ON_FILE': ('A debt is in collections.', 'Hay una deuda en cobranza.'),
    'CHARGEOFF_ON_FILE': ('There is a debt written off as unpaid.', 'Hay una deuda registrada como pérdida por falta de pago.'),
    'BANKRUPTCY_ON_FILE': ('There is a bankruptcy on the file.', 'Hay una bancarrota en el historial.'),
    'BUREAUS_DISAGREE': ('The credit bureaus show different information.', 'Las agencias de crédito muestran datos distintos.'),
    'IDENTITY_UNCONFIRMED': ('Identity could not be confirmed.', 'No se pudo confirmar la identidad.'),
    'OVER_RATE_CAP': ('This lender cannot offer a rate within the limit.', 'Este prestamista no puede ofrecer una tasa dentro del límite.'),
    'OUTSIDE_PRODUCT': ("The request does not fit this lender's products.", 'La solicitud no cumple las reglas de los productos de este prestamista.'),
    'default': ("This lender's rules do not allow an offer.", 'Las reglas de este prestamista no permiten una oferta.'),
}
for _code, (_en, _es) in _REASONS.items():
    EN['reason.' + _code] = _en
    ES['reason.' + _code] = _es
_EVENTS = {
    'event.awaiting_approval': ('Waiting for your approval. Nothing is signed.', 'Espera tu permiso. No se ha firmado nada.'),
    'event.approval': ('The person made a decision about the offer.', 'La persona tomó una decisión sobre la oferta.'),
    'event.recommend': ('Your agent recommends an offer. Nothing is signed.', 'Tu agente recomienda una oferta. No se ha firmado nada.'),
    'notice': ('Data is from the CRS sandbox: fictional test personas, not real people.', 'Datos del entorno de prueba de CRS: todas las personas son ficticias.'),
    'event.gate': ('Checking identity and credit.', 'Consultando identidad y crédito.'),
    'event.blocked': ('Stopped before any lender saw the application.', 'La solicitud se detuvo antes de enviarse a prestamistas.'),
    'event.passport': ('Sent lenders a summary without personal identity details.', 'Enviamos a los prestamistas un resumen sin datos de identidad.'),
    'event.offer': ('Offer: {amount}, {rate}% yearly rate, {months} months.', 'Oferta: {amount}, tasa anual del {rate}%, {months} meses.'),
    'event.counter': ('Asked for a lower loan cost.', 'Pidió un costo menor para el préstamo.'),
    'event.accept': ('Accepted an offer within the borrower’s limits.', 'Aceptó una oferta dentro de los límites del solicitante.'),
    'event.decline': ('No offer from this lender.', 'Este prestamista no hizo una oferta.'),
    'event.withdraw': ('An offer was withdrawn.', 'Se retiró una oferta.'),
    'event.message': ('Message checked by the exchange.', 'El mercado revisó el mensaje.'),
    'event.watchdog': ('A safeguard flagged an item for review.', 'El sistema señaló un posible problema para revisar.'),
    'event.excluded': ('A lender was removed for breaking the rules.', 'Se retiró a un prestamista por romper las reglas.'),
    'event.settlement': ('Simulated: credit check, funding and reporting.', 'Simulado: consulta completa, envío del dinero e informe a las agencias.'),
    'event.disclosure': ('Prepared your result in plain words.', 'Preparamos tu resultado en palabras sencillas.'),
    'event.no_deal': ('No offer fit the limits. Nothing was accepted.', 'Ninguna oferta cumplía los límites. No se aceptó nada.'),
    'event.allowed': ('Allowed by the exchange rules.', 'Permitido por las reglas del mercado.'),
    'event.refused': ('Blocked by the exchange rules.', 'Bloqueado por las reglas del mercado.'),
    'event.data': ('Credit and identity data used for this check.', 'Datos de crédito e identidad usados en esta consulta.'),
    'event.sources': ('CRS sandbox checks', 'Consultas del entorno de prueba de CRS'),
    'event.source_note': ('Some live checks were unavailable; saved sandbox samples were used.', 'Algunas consultas en vivo no estaban disponibles. Usamos datos guardados del entorno de prueba.'),
    'event.error': ('The session stopped. No new action was taken.', 'La sesión se detuvo. No se realizó ninguna acción nueva.'),
}
for _key, (_en, _es) in _EVENTS.items():
    EN[_key] = _en
    ES[_key] = _es
STRINGS = {"en": EN, "es": ES}


@contextmanager
def language(lang="en"):
    if lang not in LANGUAGES:
        raise ValueError("unsupported language")
    token = _LANG.set(lang)
    try:
        yield
    finally:
        _LANG.reset(token)


def t(key, **values):
    return STRINGS[_LANG.get()][key].format(**values)


def number(value, spec="g", lang=None):
    rendered = format(value, spec)
    if (lang or _LANG.get()) == "es":
        rendered = rendered.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return rendered


def money(value, lang=None):
    spec = ",.0f" if abs(value - round(value)) < .005 else ",.2f"
    rendered = number(value, spec, lang)
    return rendered + " USD" if (lang or _LANG.get()) == "es" else "$" + rendered


def fmt(value, spec=""):
    if isinstance(value, str) and re.fullmatch(r'\$[\d,]+(?:\.\d+)?', value):
        return money(float(value[1:].replace(',', '')))
    return number(value, spec or "g") if isinstance(value, (float, int)) else format(value, spec)


def count(n, word):
    return t(f"unit.{word}.{'one' if n == 1 else 'other'}", n=number(n))


def catalog():
    return STRINGS


def localized(key, lang="en", **values):
    with language(lang):
        return t(key, **values)


def event_view(event, ex, lang="en"):
    """Localized observer summary only. Never modify the signed source event."""
    from .lenders import POLICIES
    data, kind = event.get("data", {}), event["kind"]
    actor = event.get("actor", "referee")
    role = ex.roles.get(actor, "referee")
    with language(lang):
        who = POLICIES.get(actor, (None,))[0] or t("Your agent" if role == "borrower" else "Referee")
        key = 'event.' + kind
        values = {}
        if kind == 'message':
            message_type = data.get('type')
            key = 'event.' + {'OFFER': 'offer', 'COUNTER': 'counter', 'ACCEPT': 'accept', 'DECLINE': 'decline', 'WITHDRAW': 'withdraw'}.get(message_type, 'message')
            terms = data.get('terms')
            if message_type == 'OFFER' and terms and all(isinstance(terms.get(k), (int, float)) for k in ('amount', 'apr', 'term_months')):
                values = {'amount': money(terms['amount']), 'rate': number(terms['apr']), 'months': number(terms['term_months'])}
            elif message_type == 'OFFER':
                key = 'event.message'
            if message_type == 'ACCEPT' and getattr(ex, 'require_approval', False):
                key = 'event.recommend'
        if kind == 'approval':
            who = t('Your decision')
        if key not in EN:
            key = 'event.message'
        verdict = event.get('verdict')
        ok = verdict and verdict.get('ok')
        note = t('event.allowed' if ok else 'event.refused') if verdict else ''
        if kind == 'message' and data.get('type') == 'DECLINE' and 'reason.' + str(data.get('reason_code')) in EN:
            note = t('reason.' + data['reason_code'])
        return {'id': event['seq'], 'kind': kind, 'who': who, 'role': role, 'what': t(key, **values),
                'verdict': ('allowed' if ok else 'blocked') if verdict else None, 'verdict_text': note,
                'says': data.get('text') if kind == 'message' else None, 'severity': data.get('severity'),
                'simulated': kind == 'settlement' or role == 'lender', 'crs': [], 'details': [], 'steps': []}


def hood_view(view, ex, lang):
    """Spanish observer view; raw English records remain available in the audit."""
    if lang == 'en':
        return view
    out = dict(view)
    out['feed'] = [event_view(e, ex, lang) for e in ex.events]
    out['exclusions'] = [{'lender': x.get('lender', ''), 'banner': localized('event.excluded', lang)} for x in view.get('exclusions', [])]
    out['crs_products'] = [{'product': localized('event.sources', lang), 'used_for': localized('event.data', lang), 'drove': []}]
    out['simulated'] = [localized('Simulated lender', lang), localized('event.settlement', lang)]
    return out
