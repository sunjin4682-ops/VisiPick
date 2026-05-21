using Microsoft.EntityFrameworkCore;
using VisiPickData.Models;

namespace VisiPickData;

public class AppDbContext : DbContext
{
    public DbSet<InspectionResult> InspectionResults { get; set; }
    public DbSet<AgvMission> AgvMissions { get; set; }
    public DbSet<SystemEvent> SystemEvents { get; set; }

    protected override void OnConfiguring(DbContextOptionsBuilder options)  
    {
        options.UseSqlite("Data Source=visipick.db");
    }

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        // 인덱스 전략 (검색 성능)
        modelBuilder.Entity<InspectionResult>()
            .HasIndex(x => x.Timestamp);
        modelBuilder.Entity<InspectionResult>()
            .HasIndex(x => x.Class);
        modelBuilder.Entity<InspectionResult>()
            .HasIndex(x => x.GateUsed);

        modelBuilder.Entity<AgvMission>()
            .HasIndex(x => x.AgvId);

        modelBuilder.Entity<SystemEvent>()
            .HasIndex(x => x.Timestamp);
        modelBuilder.Entity<SystemEvent>()
            .HasIndex(x => x.EventType);
    }

    // WAL 모드 + 데이터 보관 정책
    public void InitializeDatabase()
    {
        Database.EnsureCreated();

        // WAL 모드 활성화 (Blazor 읽기 전용 동시 접근 안전)
        Database.ExecuteSqlRaw("PRAGMA journal_mode=WAL;");
    }

    // SystemEvents 7일 후 정리
    public void CleanupOldEvents()
    {
        var cutoff = DateTime.Now.AddDays(-7);
        SystemEvents.Where(e => e.Timestamp < cutoff)
                    .ExecuteDelete();
    }

    // InspectionResults 30일 후 아카이브
    public void CleanupOldInspections()
    {   
        var cutoff = DateTime.Now.AddDays(-30);
        InspectionResults.Where(r => r.Timestamp < cutoff)
                         .ExecuteDelete();
    }
}