from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("progetti/", views.progetti, name="progetti"),
    path("progetti/<int:pk>/", views.progetto, name="progetto"),
    path("progetti/<int:pk>/avanza/", views.progetto_avanza, name="progetto_avanza"),
    path("progetti/<int:pk>/arretra/", views.progetto_arretra, name="progetto_arretra"),
    path("progetti/<int:pk>/nota/", views.progetto_nota, name="progetto_nota"),
    path("clienti/", views.clienti, name="clienti"),
    path("clienti/<int:pk>/", views.cliente, name="cliente"),
    path("produttori/", views.produttori, name="produttori"),
    path("formule/", views.formule, name="formule"),
    path("prodotti/", views.prodotti, name="prodotti"),
    path("prodotti/<int:pk>/", views.prodotto, name="prodotto"),
    path("packaging/", views.catalogo, name="catalogo"),
    path("magazzino/", views.magazzino, name="magazzino"),
    path("listino/", views.listino, name="listino"),
    path("ordini/", views.ordini, name="ordini"),
    path("ordini/<int:pk>/", views.ordine, name="ordine"),
    path("ordini/<int:pk>/stampa/", views.ordine_stampa, name="ordine_stampa"),
    path("ordini/<int:pk>/packaging/", views.ordine_registra_packaging, name="ordine_registra_packaging"),
    path("nuovo/<str:modello>/", views.modifica, name="nuovo"),
    path("modifica/<str:modello>/<int:pk>/", views.modifica, name="modifica"),
    path("elimina/<str:modello>/<int:pk>/", views.elimina, name="elimina"),
]
