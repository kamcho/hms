from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator

HR_PAGE_SIZE = 25


def paginate_queryset(request, queryset, *, page_param='page', per_page=HR_PAGE_SIZE):
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get(page_param, 1)
    try:
        return paginator.page(page_number)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)
