document.addEventListener('DOMContentLoaded', function() {
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebarToggle');
    const mainContent = document.getElementById('mainContent');
    
    // Toggle sidebar
    sidebarToggle.addEventListener('click', function() {
        sidebar.classList.toggle('collapsed');
        
        // Save sidebar state to localStorage
        if (sidebar.classList.contains('collapsed')) {
            localStorage.setItem('sidebarState', 'collapsed');
        } else {
            localStorage.setItem('sidebarState', 'expanded');
        }
    });
    
    // Restore sidebar state from localStorage
    const sidebarState = localStorage.getItem('sidebarState');
    if (sidebarState === 'collapsed') {
        sidebar.classList.add('collapsed');
    }
    
    // Handle mobile menu
    if (window.innerWidth <= 768) {
        sidebar.classList.add('mobile');
        
        // Add mobile toggle functionality
        sidebarToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            sidebar.classList.toggle('active');
        });
        
        // Close sidebar when clicking outside on mobile
        document.addEventListener('click', function(e) {
            if (window.innerWidth <= 768 && !sidebar.contains(e.target)) {
                sidebar.classList.remove('active');
            }
        });
    }
    
    // Handle window resize
    window.addEventListener('resize', function() {
        if (window.innerWidth > 768) {
            sidebar.classList.remove('mobile', 'active');
        } else {
            sidebar.classList.add('mobile');
        }
    });
    
    // Add smooth scrolling to menu items
    const menuItems = document.querySelectorAll('.menu-item');
    menuItems.forEach(item => {
        item.addEventListener('click', function(e) {
            // Remove active class from all items
            menuItems.forEach(i => i.classList.remove('active'));
            // Add active class to clicked item
            this.classList.add('active');
        });
    });
    
    // Search functionality
    const searchInput = document.querySelector('.search-bar input');
    if (searchInput) {
        searchInput.addEventListener('input', function(e) {
            const searchTerm = e.target.value.toLowerCase();
            // Implement search functionality here
            console.log('Searching for:', searchTerm);
        });
    }
    
    // Notification badge animation
    const notifications = document.querySelector('.notifications');
    if (notifications) {
        notifications.addEventListener('click', function() {
            const badge = this.querySelector('.badge');
            if (badge) {
                badge.style.display = 'none';
            }
        });
    }
    
    // Generic submenu toggle logic
    const submenuItems = document.querySelectorAll('.menu-item.has-submenu');
    
    submenuItems.forEach(item => {
        const submenuId = item.id.replace('Menu', 'Submenu');
        const submenu = document.getElementById(submenuId);
        
        if (submenu) {
            item.addEventListener('click', function(e) {
                e.preventDefault();
                this.classList.toggle('expanded');
                submenu.classList.toggle('show');
                
                // Save state
                localStorage.setItem(`${item.id}State`, submenu.classList.contains('show') ? 'expanded' : 'collapsed');
            });
            
            // Restore state
            const state = localStorage.getItem(`${item.id}State`);
            if (state === 'expanded') {
                item.classList.add('expanded');
                submenu.classList.add('show');
            }
        }
    });
});
