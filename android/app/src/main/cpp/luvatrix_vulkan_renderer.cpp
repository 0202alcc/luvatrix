#include <jni.h>
#include <android/log.h>
#include <android/native_window_jni.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
#include <vulkan/vulkan.h>
#include <vulkan/vulkan_android.h>

#define LVX_LOGI(...) __android_log_print(ANDROID_LOG_INFO, "Luvatrix", __VA_ARGS__)
#define LVX_LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "Luvatrix", __VA_ARGS__)

namespace {

struct Rgba {
    int r = 0;
    int g = 0;
    int b = 0;
    int a = 255;
};

struct CirclePrimitive {
    double cx = 0.0;
    double cy = 0.0;
    double radius = 0.0;
    Rgba fill;
    Rgba stroke;
    double stroke_width = 0.0;
};

struct RectPrimitive {
    double x = 0.0;
    double y = 0.0;
    double width = 0.0;
    double height = 0.0;
    Rgba color;
};

struct TextPrimitive {
    std::string text;
    double x = 0.0;
    double y = 0.0;
    double size = 12.0;
    Rgba color;
};

struct BitmapFont {
    int width = 5;
    int height = 7;
    int advance = 6;
    std::unordered_map<char, std::vector<uint32_t>> glyphs;
    bool loaded = false;
};

struct GlyphBitmap {
    int width = 5;
    int height = 7;
    int advance = 6;
    std::vector<uint32_t> rows;
};

struct ParsedScene {
    Rgba background;
    std::vector<RectPrimitive> rects;
    std::vector<CirclePrimitive> circles;
    std::vector<TextPrimitive> texts;
};

struct VulkanState {
    ANativeWindow* window = nullptr;
    VkInstance instance = VK_NULL_HANDLE;
    VkSurfaceKHR surface = VK_NULL_HANDLE;
    VkPhysicalDevice physical = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkQueue queue = VK_NULL_HANDLE;
    uint32_t queue_family = 0;
    VkSwapchainKHR swapchain = VK_NULL_HANDLE;
    VkFormat swapchain_format = VK_FORMAT_B8G8R8A8_UNORM;
    VkExtent2D extent{0, 0};
    std::vector<VkImage> images;
    std::vector<VkImageView> image_views;
    VkRenderPass render_pass = VK_NULL_HANDLE;
    std::vector<VkFramebuffer> framebuffers;
    VkCommandPool command_pool = VK_NULL_HANDLE;
    std::vector<VkCommandBuffer> command_buffers;
    VkSemaphore image_available = VK_NULL_HANDLE;
    VkSemaphore render_finished = VK_NULL_HANDLE;
    VkBuffer staging_buffer = VK_NULL_HANDLE;
    VkDeviceMemory staging_memory = VK_NULL_HANDLE;
    VkDeviceSize staging_capacity = 0;
    int desired_width = 0;
    int desired_height = 0;
    bool initialized = false;
};

std::mutex g_mutex;
VulkanState g_vk;
BitmapFont g_bitmap_font;

int count_nodes(const std::string& scene_json) {
    int count = 0;
    const std::string needle = "\"type\"";
    std::string::size_type pos = 0;
    while ((pos = scene_json.find(needle, pos)) != std::string::npos) {
        ++count;
        pos += needle.size();
    }
    return count;
}

int clamp255(int v) {
    return std::max(0, std::min(255, v));
}

std::optional<double> number_after(const std::string& text, std::string::size_type pos) {
    if (pos == std::string::npos) return std::nullopt;
    while (pos < text.size() && text[pos] != '-' && text[pos] != '+' && text[pos] != '.' && (text[pos] < '0' || text[pos] > '9')) {
        ++pos;
    }
    if (pos >= text.size()) return std::nullopt;
    char* end = nullptr;
    double value = std::strtod(text.c_str() + pos, &end);
    if (end == text.c_str() + pos) return std::nullopt;
    return value;
}

Rgba parse_color_array(const std::string& json, const std::string& key, Rgba fallback) {
    auto key_pos = json.find("\"" + key + "\"");
    if (key_pos == std::string::npos) return fallback;
    auto open = json.find('[', key_pos);
    auto close = json.find(']', open);
    if (open == std::string::npos || close == std::string::npos) return fallback;
    std::array<int, 4> values{fallback.r, fallback.g, fallback.b, fallback.a};
    auto pos = open + 1;
    for (int i = 0; i < 4 && pos < close; ++i) {
        auto value = number_after(json, pos);
        if (!value.has_value()) break;
        values[i] = clamp255(static_cast<int>(*value));
        auto comma = json.find(',', pos);
        if (comma == std::string::npos || comma > close) break;
        pos = comma + 1;
    }
    return Rgba{values[0], values[1], values[2], values[3]};
}

Rgba parse_scene_background(const std::string& json) {
    Rgba fallback = parse_color_array(json, "color", Rgba{0, 0, 0, 255});
    auto shader = json.find("\"shader\":\"full_suite_background\"");
    if (shader == std::string::npos) return fallback;
    auto uniforms = json.find("\"uniforms\"", shader);
    auto open = json.find('[', uniforms);
    if (open == std::string::npos) return fallback;
    auto t = number_after(json, open + 1).value_or(0.0);
    auto comma1 = json.find(',', open + 1);
    auto rotation = number_after(json, comma1 == std::string::npos ? open + 1 : comma1 + 1).value_or(0.0);
    auto comma2 = comma1 == std::string::npos ? std::string::npos : json.find(',', comma1 + 1);
    auto scroll_y = number_after(json, comma2 == std::string::npos ? open + 1 : comma2 + 1).value_or(0.0);
    int ti = static_cast<int>(t);
    int base_r = (ti * 3 + 35) % 255;
    int base_g = (ti * 2 + 70) % 255;
    int base_b = (ti * 4 + 20) % 255;
    int rotate_boost = static_cast<int>(std::max(-30.0, std::min(30.0, rotation * 2.0)));
    int scroll_boost = static_cast<int>(std::max(-40.0, std::min(40.0, scroll_y * 0.5)));
    return Rgba{clamp255(base_r + rotate_boost), clamp255(base_g + scroll_boost), clamp255(base_b), 255};
}

std::string::size_type value_pos_after_key(const std::string& json, const std::string& key) {
    auto key_pos = json.find("\"" + key + "\"");
    if (key_pos == std::string::npos) return std::string::npos;
    auto colon = json.find(':', key_pos);
    return colon == std::string::npos ? std::string::npos : colon + 1;
}

double parse_number_key(const std::string& json, const std::string& key, double fallback = 0.0) {
    auto pos = value_pos_after_key(json, key);
    return number_after(json, pos).value_or(fallback);
}

std::string parse_string_key(const std::string& json, const std::string& key) {
    auto pos = value_pos_after_key(json, key);
    if (pos == std::string::npos) return "";
    auto open = json.find('"', pos);
    if (open == std::string::npos) return "";
    std::string out;
    bool escape = false;
    for (auto i = open + 1; i < json.size(); ++i) {
        char ch = json[i];
        if (escape) {
            switch (ch) {
                case 'n': out.push_back('\n'); break;
                case 't': out.push_back('\t'); break;
                case 'r': out.push_back('\r'); break;
                default: out.push_back(ch); break;
            }
            escape = false;
        } else if (ch == '\\') {
            escape = true;
        } else if (ch == '"') {
            break;
        } else {
            out.push_back(ch);
        }
    }
    return out;
}

std::string parse_type(const std::string& node) {
    return parse_string_key(node, "type");
}

std::vector<std::string> parse_node_objects(const std::string& json) {
    std::vector<std::string> out;
    int depth = 0;
    bool in_string = false;
    bool escape = false;
    std::string::size_type start = std::string::npos;
    for (std::string::size_type i = 0; i < json.size(); ++i) {
        char ch = json[i];
        if (in_string) {
            if (escape) {
                escape = false;
            } else if (ch == '\\') {
                escape = true;
            } else if (ch == '"') {
                in_string = false;
            }
            continue;
        }
        if (ch == '"') {
            in_string = true;
        } else if (ch == '{') {
            if (depth == 0) start = i;
            ++depth;
        } else if (ch == '}') {
            --depth;
            if (depth == 0 && start != std::string::npos) {
                out.push_back(json.substr(start, i - start + 1));
                start = std::string::npos;
            }
        }
    }
    return out;
}

ParsedScene parse_scene(const std::string& json) {
    ParsedScene scene;
    scene.background = parse_scene_background(json);
    for (const auto& node : parse_node_objects(json)) {
        const std::string type = parse_type(node);
        if (type == "clear") {
            scene.background = parse_color_array(node, "color", scene.background);
        } else if (type == "shader_rect" && parse_string_key(node, "shader") == "full_suite_background") {
            scene.background = parse_scene_background(node);
        } else if (type == "rect") {
            scene.rects.push_back(RectPrimitive{
                parse_number_key(node, "x"),
                parse_number_key(node, "y"),
                parse_number_key(node, "w"),
                parse_number_key(node, "h"),
                parse_color_array(node, "color", Rgba{255, 255, 255, 255}),
            });
        } else if (type == "circle") {
            scene.circles.push_back(CirclePrimitive{
                parse_number_key(node, "cx"),
                parse_number_key(node, "cy"),
                parse_number_key(node, "r"),
                parse_color_array(node, "fill", Rgba{255, 255, 255, 255}),
                parse_color_array(node, "stroke", Rgba{255, 255, 255, 255}),
                parse_number_key(node, "stroke_width"),
            });
        } else if (type == "text") {
            scene.texts.push_back(TextPrimitive{
                parse_string_key(node, "text"),
                parse_number_key(node, "x"),
                parse_number_key(node, "y"),
                parse_number_key(node, "size", 12.0),
                parse_color_array(node, "color", Rgba{255, 255, 255, 255}),
            });
        }
    }
    return scene;
}

void destroy_swapchain(VulkanState& vk) {
    if (vk.device != VK_NULL_HANDLE) {
        vkDeviceWaitIdle(vk.device);
        for (auto framebuffer : vk.framebuffers) vkDestroyFramebuffer(vk.device, framebuffer, nullptr);
        vk.framebuffers.clear();
        if (!vk.command_buffers.empty() && vk.command_pool != VK_NULL_HANDLE) {
            vkFreeCommandBuffers(vk.device, vk.command_pool, static_cast<uint32_t>(vk.command_buffers.size()), vk.command_buffers.data());
            vk.command_buffers.clear();
        }
        if (vk.command_pool != VK_NULL_HANDLE) {
            vkDestroyCommandPool(vk.device, vk.command_pool, nullptr);
            vk.command_pool = VK_NULL_HANDLE;
        }
        if (vk.render_pass != VK_NULL_HANDLE) {
            vkDestroyRenderPass(vk.device, vk.render_pass, nullptr);
            vk.render_pass = VK_NULL_HANDLE;
        }
        for (auto view : vk.image_views) vkDestroyImageView(vk.device, view, nullptr);
        vk.image_views.clear();
        if (vk.swapchain != VK_NULL_HANDLE) {
            vkDestroySwapchainKHR(vk.device, vk.swapchain, nullptr);
            vk.swapchain = VK_NULL_HANDLE;
        }
    }
    vk.images.clear();
    vk.extent = VkExtent2D{0, 0};
}

void destroy_vulkan(VulkanState& vk) {
    destroy_swapchain(vk);
    if (vk.device != VK_NULL_HANDLE) {
        if (vk.image_available != VK_NULL_HANDLE) vkDestroySemaphore(vk.device, vk.image_available, nullptr);
        if (vk.render_finished != VK_NULL_HANDLE) vkDestroySemaphore(vk.device, vk.render_finished, nullptr);
        if (vk.staging_buffer != VK_NULL_HANDLE) vkDestroyBuffer(vk.device, vk.staging_buffer, nullptr);
        if (vk.staging_memory != VK_NULL_HANDLE) vkFreeMemory(vk.device, vk.staging_memory, nullptr);
        vkDestroyDevice(vk.device, nullptr);
    }
    if (vk.surface != VK_NULL_HANDLE && vk.instance != VK_NULL_HANDLE) vkDestroySurfaceKHR(vk.instance, vk.surface, nullptr);
    if (vk.instance != VK_NULL_HANDLE) vkDestroyInstance(vk.instance, nullptr);
    if (vk.window != nullptr) ANativeWindow_release(vk.window);
    vk = VulkanState{};
}

bool create_instance(VulkanState& vk) {
    uint32_t extension_count = 0;
    VkResult enumerate = vkEnumerateInstanceExtensionProperties(nullptr, &extension_count, nullptr);
    if (enumerate != VK_SUCCESS) {
        LVX_LOGE("vkEnumerateInstanceExtensionProperties failed before create_instance: %d", enumerate);
        return false;
    }
    std::vector<VkExtensionProperties> available(extension_count);
    vkEnumerateInstanceExtensionProperties(nullptr, &extension_count, available.data());
    bool has_surface = false;
    bool has_android_surface = false;
    for (const auto& extension : available) {
        if (std::strcmp(extension.extensionName, "VK_KHR_surface") == 0) has_surface = true;
        if (std::strcmp(extension.extensionName, "VK_KHR_android_surface") == 0) has_android_surface = true;
    }
    if (!has_surface || !has_android_surface) {
        LVX_LOGE(
            "required Vulkan surface extensions missing: VK_KHR_surface=%d VK_KHR_android_surface=%d extension_count=%u",
            has_surface ? 1 : 0,
            has_android_surface ? 1 : 0,
            extension_count
        );
        return false;
    }
    const char* extensions[] = {"VK_KHR_surface", "VK_KHR_android_surface"};
    VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
    app.pApplicationName = "Luvatrix";
    app.applicationVersion = VK_MAKE_VERSION(0, 1, 0);
    app.pEngineName = "Luvatrix";
    app.engineVersion = VK_MAKE_VERSION(0, 1, 0);
    app.apiVersion = VK_API_VERSION_1_0;
    VkInstanceCreateInfo ci{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    ci.pApplicationInfo = &app;
    ci.enabledExtensionCount = 2;
    ci.ppEnabledExtensionNames = extensions;
    VkResult result = vkCreateInstance(&ci, nullptr, &vk.instance);
    if (result != VK_SUCCESS) {
        LVX_LOGE("vkCreateInstance failed: %d", result);
        return false;
    }
    return true;
}

bool create_surface(VulkanState& vk) {
    if (vk.window == nullptr) {
        LVX_LOGE("vkCreateAndroidSurfaceKHR skipped: null ANativeWindow");
        return false;
    }
    if (vk.desired_width > 0 && vk.desired_height > 0) {
        int result = ANativeWindow_setBuffersGeometry(vk.window, vk.desired_width, vk.desired_height, 0);
        if (result != 0) {
            LVX_LOGE(
                "ANativeWindow_setBuffersGeometry failed: %d requested=%dx%d",
                result,
                vk.desired_width,
                vk.desired_height
            );
        }
    }
    int window_width = ANativeWindow_getWidth(vk.window);
    int window_height = ANativeWindow_getHeight(vk.window);
    LVX_LOGI(
        "creating Android Vulkan surface window=%p size=%dx%d requested=%dx%d",
        vk.window,
        window_width,
        window_height,
        vk.desired_width,
        vk.desired_height
    );
    VkAndroidSurfaceCreateInfoKHR ci{VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR};
    ci.window = vk.window;
    VkResult result = vkCreateAndroidSurfaceKHR(vk.instance, &ci, nullptr, &vk.surface);
    if (result != VK_SUCCESS) {
        LVX_LOGE("vkCreateAndroidSurfaceKHR failed: %d", result);
        return false;
    }
    return true;
}

bool pick_device(VulkanState& vk) {
    uint32_t count = 0;
    vkEnumeratePhysicalDevices(vk.instance, &count, nullptr);
    if (count == 0) return false;
    std::vector<VkPhysicalDevice> devices(count);
    vkEnumeratePhysicalDevices(vk.instance, &count, devices.data());
    for (auto device : devices) {
        uint32_t q_count = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(device, &q_count, nullptr);
        std::vector<VkQueueFamilyProperties> queues(q_count);
        vkGetPhysicalDeviceQueueFamilyProperties(device, &q_count, queues.data());
        for (uint32_t i = 0; i < q_count; ++i) {
            VkBool32 present = VK_FALSE;
            vkGetPhysicalDeviceSurfaceSupportKHR(device, i, vk.surface, &present);
            if ((queues[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) && present) {
                vk.physical = device;
                vk.queue_family = i;
                return true;
            }
        }
    }
    return false;
}

bool create_device(VulkanState& vk) {
    float priority = 1.0f;
    VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};
    qci.queueFamilyIndex = vk.queue_family;
    qci.queueCount = 1;
    qci.pQueuePriorities = &priority;
    const char* extensions[] = {"VK_KHR_swapchain"};
    VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};
    dci.queueCreateInfoCount = 1;
    dci.pQueueCreateInfos = &qci;
    dci.enabledExtensionCount = 1;
    dci.ppEnabledExtensionNames = extensions;
    if (vkCreateDevice(vk.physical, &dci, nullptr, &vk.device) != VK_SUCCESS) return false;
    vkGetDeviceQueue(vk.device, vk.queue_family, 0, &vk.queue);
    VkSemaphoreCreateInfo sci{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    return vkCreateSemaphore(vk.device, &sci, nullptr, &vk.image_available) == VK_SUCCESS
        && vkCreateSemaphore(vk.device, &sci, nullptr, &vk.render_finished) == VK_SUCCESS;
}

VkSurfaceFormatKHR choose_format(const std::vector<VkSurfaceFormatKHR>& formats) {
    for (const auto& format : formats) {
        if (format.format == VK_FORMAT_B8G8R8A8_UNORM && format.colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR) return format;
    }
    return formats[0];
}

bool create_swapchain(VulkanState& vk) {
    VkSurfaceCapabilitiesKHR caps{};
    vkGetPhysicalDeviceSurfaceCapabilitiesKHR(vk.physical, vk.surface, &caps);
    uint32_t format_count = 0;
    vkGetPhysicalDeviceSurfaceFormatsKHR(vk.physical, vk.surface, &format_count, nullptr);
    if (format_count == 0) return false;
    std::vector<VkSurfaceFormatKHR> formats(format_count);
    vkGetPhysicalDeviceSurfaceFormatsKHR(vk.physical, vk.surface, &format_count, formats.data());
    auto format = choose_format(formats);
    vk.swapchain_format = format.format;
    if (caps.currentExtent.width != UINT32_MAX) {
        vk.extent = caps.currentExtent;
    } else {
        vk.extent = VkExtent2D{
            static_cast<uint32_t>(std::max(1, ANativeWindow_getWidth(vk.window))),
            static_cast<uint32_t>(std::max(1, ANativeWindow_getHeight(vk.window))),
        };
    }
    uint32_t image_count = caps.minImageCount + 1;
    if (caps.maxImageCount > 0 && image_count > caps.maxImageCount) image_count = caps.maxImageCount;
    VkSwapchainCreateInfoKHR sci{VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR};
    sci.surface = vk.surface;
    sci.minImageCount = image_count;
    sci.imageFormat = vk.swapchain_format;
    sci.imageColorSpace = format.colorSpace;
    sci.imageExtent = vk.extent;
    sci.imageArrayLayers = 1;
    sci.imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    sci.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
    sci.preTransform = caps.currentTransform;
    sci.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    sci.presentMode = VK_PRESENT_MODE_FIFO_KHR;
    sci.clipped = VK_TRUE;
    if (vkCreateSwapchainKHR(vk.device, &sci, nullptr, &vk.swapchain) != VK_SUCCESS) return false;
    uint32_t actual_count = 0;
    vkGetSwapchainImagesKHR(vk.device, vk.swapchain, &actual_count, nullptr);
    vk.images.resize(actual_count);
    vkGetSwapchainImagesKHR(vk.device, vk.swapchain, &actual_count, vk.images.data());
    return true;
}

bool create_render_resources(VulkanState& vk) {
    for (auto image : vk.images) {
        VkImageViewCreateInfo iv{VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO};
        iv.image = image;
        iv.viewType = VK_IMAGE_VIEW_TYPE_2D;
        iv.format = vk.swapchain_format;
        iv.components = {VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY, VK_COMPONENT_SWIZZLE_IDENTITY};
        iv.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        iv.subresourceRange.baseMipLevel = 0;
        iv.subresourceRange.levelCount = 1;
        iv.subresourceRange.baseArrayLayer = 0;
        iv.subresourceRange.layerCount = 1;
        VkImageView view = VK_NULL_HANDLE;
        if (vkCreateImageView(vk.device, &iv, nullptr, &view) != VK_SUCCESS) return false;
        vk.image_views.push_back(view);
    }
    VkAttachmentDescription color{};
    color.format = vk.swapchain_format;
    color.samples = VK_SAMPLE_COUNT_1_BIT;
    color.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    color.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    color.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    color.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    color.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    color.finalLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
    VkAttachmentReference ref{};
    ref.attachment = 0;
    ref.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &ref;
    VkRenderPassCreateInfo rp{VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO};
    rp.attachmentCount = 1;
    rp.pAttachments = &color;
    rp.subpassCount = 1;
    rp.pSubpasses = &subpass;
    if (vkCreateRenderPass(vk.device, &rp, nullptr, &vk.render_pass) != VK_SUCCESS) return false;
    for (auto view : vk.image_views) {
        VkFramebufferCreateInfo fb{VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO};
        fb.renderPass = vk.render_pass;
        fb.attachmentCount = 1;
        fb.pAttachments = &view;
        fb.width = vk.extent.width;
        fb.height = vk.extent.height;
        fb.layers = 1;
        VkFramebuffer framebuffer = VK_NULL_HANDLE;
        if (vkCreateFramebuffer(vk.device, &fb, nullptr, &framebuffer) != VK_SUCCESS) return false;
        vk.framebuffers.push_back(framebuffer);
    }
    VkCommandPoolCreateInfo cp{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    cp.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    cp.queueFamilyIndex = vk.queue_family;
    if (vkCreateCommandPool(vk.device, &cp, nullptr, &vk.command_pool) != VK_SUCCESS) return false;
    vk.command_buffers.resize(vk.images.size());
    VkCommandBufferAllocateInfo alloc{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    alloc.commandPool = vk.command_pool;
    alloc.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    alloc.commandBufferCount = static_cast<uint32_t>(vk.command_buffers.size());
    return vkAllocateCommandBuffers(vk.device, &alloc, vk.command_buffers.data()) == VK_SUCCESS;
}

bool ensure_vulkan(VulkanState& vk) {
    if (vk.initialized) return true;
    if (vk.window == nullptr) return false;
    if (!create_instance(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_instance");
        destroy_vulkan(vk);
        return false;
    }
    if (!create_surface(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_surface");
        destroy_vulkan(vk);
        return false;
    }
    if (!pick_device(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: pick_device");
        destroy_vulkan(vk);
        return false;
    }
    if (!create_device(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_device");
        destroy_vulkan(vk);
        return false;
    }
    if (!create_swapchain(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_swapchain");
        destroy_vulkan(vk);
        return false;
    }
    if (!create_render_resources(vk)) {
        LVX_LOGE("failed to initialize Android Vulkan scene background renderer: create_render_resources");
        destroy_vulkan(vk);
        return false;
    }
    vk.initialized = true;
    LVX_LOGI("luvatrix Android Vulkan scene background ready extent=%ux%u", vk.extent.width, vk.extent.height);
    return true;
}

uint32_t pack_bgra(Rgba color) {
    return static_cast<uint32_t>(clamp255(color.b))
        | (static_cast<uint32_t>(clamp255(color.g)) << 8)
        | (static_cast<uint32_t>(clamp255(color.r)) << 16)
        | (static_cast<uint32_t>(clamp255(color.a)) << 24);
}

void blend_pixel(std::vector<uint32_t>& pixels, int width, int height, int x, int y, Rgba src) {
    if (x < 0 || y < 0 || x >= width || y >= height || src.a <= 0) return;
    uint32_t& dst = pixels[static_cast<size_t>(y) * static_cast<size_t>(width) + static_cast<size_t>(x)];
    if (src.a >= 255) {
        dst = pack_bgra(src);
        return;
    }
    int db = static_cast<int>(dst & 0xff);
    int dg = static_cast<int>((dst >> 8) & 0xff);
    int dr = static_cast<int>((dst >> 16) & 0xff);
    int da = static_cast<int>((dst >> 24) & 0xff);
    int inv = 255 - clamp255(src.a);
    int out_a = clamp255(src.a + (da * inv + 127) / 255);
    int out_r = (src.r * src.a + dr * inv + 127) / 255;
    int out_g = (src.g * src.a + dg * inv + 127) / 255;
    int out_b = (src.b * src.a + db * inv + 127) / 255;
    dst = pack_bgra(Rgba{out_r, out_g, out_b, out_a});
}

void draw_rect_pixels(
    std::vector<uint32_t>& pixels,
    int width,
    int height,
    double scale_x,
    double scale_y,
    const RectPrimitive& rect
) {
    int x0 = static_cast<int>(std::floor(rect.x * scale_x));
    int y0 = static_cast<int>(std::floor(rect.y * scale_y));
    int x1 = static_cast<int>(std::ceil((rect.x + rect.width) * scale_x));
    int y1 = static_cast<int>(std::ceil((rect.y + rect.height) * scale_y));
    x0 = std::max(0, std::min(width, x0));
    x1 = std::max(0, std::min(width, x1));
    y0 = std::max(0, std::min(height, y0));
    y1 = std::max(0, std::min(height, y1));
    for (int y = y0; y < y1; ++y) {
        for (int x = x0; x < x1; ++x) blend_pixel(pixels, width, height, x, y, rect.color);
    }
}

void draw_circle_pixels(
    std::vector<uint32_t>& pixels,
    int width,
    int height,
    double scale_x,
    double scale_y,
    const CirclePrimitive& circle
) {
    double scale = std::min(scale_x, scale_y);
    double cx = circle.cx * scale_x;
    double cy = circle.cy * scale_y;
    double radius = std::max(0.0, circle.radius * scale);
    double stroke = std::max(0.0, circle.stroke_width * scale);
    if (radius <= 0.0) return;
    int x0 = std::max(0, static_cast<int>(std::floor(cx - radius - stroke - 1.0)));
    int x1 = std::min(width - 1, static_cast<int>(std::ceil(cx + radius + stroke + 1.0)));
    int y0 = std::max(0, static_cast<int>(std::floor(cy - radius - stroke - 1.0)));
    int y1 = std::min(height - 1, static_cast<int>(std::ceil(cy + radius + stroke + 1.0)));
    double outer = radius + stroke * 0.5;
    double inner_stroke = std::max(0.0, radius - stroke * 0.5);
    double fill_limit = stroke > 0.0 ? inner_stroke : radius;
    for (int y = y0; y <= y1; ++y) {
        for (int x = x0; x <= x1; ++x) {
            double dx = (static_cast<double>(x) + 0.5) - cx;
            double dy = (static_cast<double>(y) + 0.5) - cy;
            double dist = std::sqrt(dx * dx + dy * dy);
            if (dist <= fill_limit) {
                blend_pixel(pixels, width, height, x, y, circle.fill);
            } else if (stroke > 0.0 && dist <= outer) {
                blend_pixel(pixels, width, height, x, y, circle.stroke);
            }
        }
    }
}

std::string trim_copy(const std::string& value) {
    auto start = value.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    auto end = value.find_last_not_of(" \t\r\n");
    return value.substr(start, end - start + 1);
}

std::optional<int> parse_int_value(const std::string& value) {
    char* end = nullptr;
    long parsed = std::strtol(value.c_str(), &end, 10);
    if (end == value.c_str()) return std::nullopt;
    return static_cast<int>(parsed);
}

std::optional<char> parse_glyph_key(const std::string& raw_key) {
    std::string key = trim_copy(raw_key);
    if (key == "space") return ' ';
    if (key == "colon") return ':';
    if (key == "period") return '.';
    if (key == "comma") return ',';
    if (key == "dash") return '-';
    if (key == "underscore") return '_';
    if (key == "equals") return '=';
    if (key == "pipe") return '|';
    if (key == "slash") return '/';
    if (key.rfind("U+", 0) == 0 || key.rfind("u+", 0) == 0) {
        char* end = nullptr;
        long code = std::strtol(key.c_str() + 2, &end, 16);
        if (end == key.c_str() + 2 || code < 0 || code > 127) return std::nullopt;
        return static_cast<char>(code);
    }
    if (key.size() == 1) return key[0];
    return std::nullopt;
}

bool parse_bitmap_font_table(const std::string& source, BitmapFont& out) {
    BitmapFont parsed;
    size_t pos = 0;
    while (pos <= source.size()) {
        size_t next = source.find('\n', pos);
        std::string line = trim_copy(source.substr(pos, next == std::string::npos ? std::string::npos : next - pos));
        pos = next == std::string::npos ? source.size() + 1 : next + 1;
        if (line.empty() || line[0] == '#') continue;
        auto eq = line.find('=');
        if (eq == std::string::npos) continue;
        std::string key = trim_copy(line.substr(0, eq));
        std::string value = trim_copy(line.substr(eq + 1));
        if (key == "width") {
            parsed.width = std::max(1, std::min(32, parse_int_value(value).value_or(parsed.width)));
            continue;
        }
        if (key == "height") {
            parsed.height = std::max(1, std::min(64, parse_int_value(value).value_or(parsed.height)));
            continue;
        }
        if (key == "advance") {
            parsed.advance = std::max(1, std::min(64, parse_int_value(value).value_or(parsed.advance)));
            continue;
        }
        auto glyph_key = parse_glyph_key(key);
        if (!glyph_key.has_value()) continue;
        std::vector<uint32_t> rows;
        size_t row_pos = 0;
        while (row_pos <= value.size()) {
            size_t comma = value.find(',', row_pos);
            std::string token = trim_copy(value.substr(row_pos, comma == std::string::npos ? std::string::npos : comma - row_pos));
            row_pos = comma == std::string::npos ? value.size() + 1 : comma + 1;
            if (token.empty()) continue;
            char* end = nullptr;
            unsigned long row = std::strtoul(token.c_str(), &end, 16);
            if (end == token.c_str()) {
                rows.clear();
                break;
            }
            rows.push_back(static_cast<uint32_t>(row));
        }
        if (static_cast<int>(rows.size()) == parsed.height) {
            parsed.glyphs[*glyph_key] = rows;
        }
    }
    if (parsed.glyphs.empty()) return false;
    parsed.loaded = true;
    out = std::move(parsed);
    return true;
}

std::array<uint8_t, 7> builtin_glyph_rows(char raw) {
    char ch = raw >= 'a' && raw <= 'z' ? static_cast<char>(raw - 'a' + 'A') : raw;
    switch (ch) {
        case 'A': return {0x0e,0x11,0x11,0x1f,0x11,0x11,0x11};
        case 'B': return {0x1e,0x11,0x11,0x1e,0x11,0x11,0x1e};
        case 'C': return {0x0e,0x11,0x10,0x10,0x10,0x11,0x0e};
        case 'D': return {0x1e,0x11,0x11,0x11,0x11,0x11,0x1e};
        case 'E': return {0x1f,0x10,0x10,0x1e,0x10,0x10,0x1f};
        case 'F': return {0x1f,0x10,0x10,0x1e,0x10,0x10,0x10};
        case 'G': return {0x0e,0x11,0x10,0x17,0x11,0x11,0x0f};
        case 'H': return {0x11,0x11,0x11,0x1f,0x11,0x11,0x11};
        case 'I': return {0x0e,0x04,0x04,0x04,0x04,0x04,0x0e};
        case 'J': return {0x07,0x02,0x02,0x02,0x12,0x12,0x0c};
        case 'K': return {0x11,0x12,0x14,0x18,0x14,0x12,0x11};
        case 'L': return {0x10,0x10,0x10,0x10,0x10,0x10,0x1f};
        case 'M': return {0x11,0x1b,0x15,0x15,0x11,0x11,0x11};
        case 'N': return {0x11,0x19,0x15,0x13,0x11,0x11,0x11};
        case 'O': return {0x0e,0x11,0x11,0x11,0x11,0x11,0x0e};
        case 'P': return {0x1e,0x11,0x11,0x1e,0x10,0x10,0x10};
        case 'Q': return {0x0e,0x11,0x11,0x11,0x15,0x12,0x0d};
        case 'R': return {0x1e,0x11,0x11,0x1e,0x14,0x12,0x11};
        case 'S': return {0x0f,0x10,0x10,0x0e,0x01,0x01,0x1e};
        case 'T': return {0x1f,0x04,0x04,0x04,0x04,0x04,0x04};
        case 'U': return {0x11,0x11,0x11,0x11,0x11,0x11,0x0e};
        case 'V': return {0x11,0x11,0x11,0x11,0x11,0x0a,0x04};
        case 'W': return {0x11,0x11,0x11,0x15,0x15,0x15,0x0a};
        case 'X': return {0x11,0x11,0x0a,0x04,0x0a,0x11,0x11};
        case 'Y': return {0x11,0x11,0x0a,0x04,0x04,0x04,0x04};
        case 'Z': return {0x1f,0x01,0x02,0x04,0x08,0x10,0x1f};
        case '0': return {0x0e,0x11,0x13,0x15,0x19,0x11,0x0e};
        case '1': return {0x04,0x0c,0x04,0x04,0x04,0x04,0x0e};
        case '2': return {0x0e,0x11,0x01,0x02,0x04,0x08,0x1f};
        case '3': return {0x1e,0x01,0x01,0x0e,0x01,0x01,0x1e};
        case '4': return {0x02,0x06,0x0a,0x12,0x1f,0x02,0x02};
        case '5': return {0x1f,0x10,0x10,0x1e,0x01,0x01,0x1e};
        case '6': return {0x0e,0x10,0x10,0x1e,0x11,0x11,0x0e};
        case '7': return {0x1f,0x01,0x02,0x04,0x08,0x08,0x08};
        case '8': return {0x0e,0x11,0x11,0x0e,0x11,0x11,0x0e};
        case '9': return {0x0e,0x11,0x11,0x0f,0x01,0x01,0x0e};
        case ':': return {0x00,0x04,0x04,0x00,0x04,0x04,0x00};
        case '.': return {0x00,0x00,0x00,0x00,0x00,0x0c,0x0c};
        case ',': return {0x00,0x00,0x00,0x00,0x04,0x04,0x08};
        case '-': return {0x00,0x00,0x00,0x1f,0x00,0x00,0x00};
        case '_': return {0x00,0x00,0x00,0x00,0x00,0x00,0x1f};
        case '=': return {0x00,0x00,0x1f,0x00,0x1f,0x00,0x00};
        case '|': return {0x04,0x04,0x04,0x04,0x04,0x04,0x04};
        case '/': return {0x01,0x01,0x02,0x04,0x08,0x10,0x10};
        case ' ': return {0x00,0x00,0x00,0x00,0x00,0x00,0x00};
        default: return {0x1f,0x11,0x05,0x02,0x04,0x00,0x04};
    }
}

GlyphBitmap glyph_bitmap(char raw) {
    char ch = raw >= 'a' && raw <= 'z' ? static_cast<char>(raw - 'a' + 'A') : raw;
    if (g_bitmap_font.loaded) {
        auto found = g_bitmap_font.glyphs.find(ch);
        if (found == g_bitmap_font.glyphs.end() && raw >= 'a' && raw <= 'z') {
            found = g_bitmap_font.glyphs.find(raw);
        }
        if (found != g_bitmap_font.glyphs.end()) {
            return GlyphBitmap{g_bitmap_font.width, g_bitmap_font.height, g_bitmap_font.advance, found->second};
        }
    }
    auto builtin = builtin_glyph_rows(raw);
    return GlyphBitmap{5, 7, 6, std::vector<uint32_t>(builtin.begin(), builtin.end())};
}

void draw_text_pixels(
    std::vector<uint32_t>& pixels,
    int width,
    int height,
    double scale_x,
    double scale_y,
    const TextPrimitive& text
) {
    if (text.text.empty() || text.color.a <= 0) return;
    double scale = std::max(1.0, std::min(scale_x, scale_y));
    int x_cursor = static_cast<int>(std::round(text.x * scale_x));
    int y_top = static_cast<int>(std::round(text.y * scale_y));
    int line_start = x_cursor;
    for (char ch : text.text) {
        GlyphBitmap glyph = glyph_bitmap(ch);
        int px = std::max(1, static_cast<int>(std::round(text.size * scale / static_cast<double>(std::max(1, glyph.height)))));
        if (ch == '\n') {
            x_cursor = line_start;
            y_top += px * (glyph.height + 2);
            continue;
        }
        for (int row = 0; row < glyph.height && row < static_cast<int>(glyph.rows.size()); ++row) {
            for (int col = 0; col < glyph.width; ++col) {
                if ((glyph.rows[row] & (1u << (glyph.width - 1 - col))) == 0) continue;
                int x0 = x_cursor + col * px;
                int y0 = y_top + row * px;
                for (int yy = 0; yy < px; ++yy) {
                    for (int xx = 0; xx < px; ++xx) {
                        blend_pixel(pixels, width, height, x0 + xx, y0 + yy, text.color);
                    }
                }
            }
        }
        x_cursor += px * glyph.advance;
    }
}

std::vector<uint32_t> rasterize_scene_pixels(const ParsedScene& scene, int width, int height, int logical_width, int logical_height) {
    std::vector<uint32_t> pixels(static_cast<size_t>(width) * static_cast<size_t>(height), pack_bgra(scene.background));
    double scale_x = static_cast<double>(width) / static_cast<double>(std::max(1, logical_width));
    double scale_y = static_cast<double>(height) / static_cast<double>(std::max(1, logical_height));
    for (const auto& rect : scene.rects) draw_rect_pixels(pixels, width, height, scale_x, scale_y, rect);
    for (const auto& circle : scene.circles) draw_circle_pixels(pixels, width, height, scale_x, scale_y, circle);
    for (const auto& text : scene.texts) draw_text_pixels(pixels, width, height, scale_x, scale_y, text);
    return pixels;
}

uint32_t find_memory_type(VulkanState& vk, uint32_t bits, VkMemoryPropertyFlags flags) {
    VkPhysicalDeviceMemoryProperties props{};
    vkGetPhysicalDeviceMemoryProperties(vk.physical, &props);
    for (uint32_t i = 0; i < props.memoryTypeCount; ++i) {
        if ((bits & (1u << i)) && (props.memoryTypes[i].propertyFlags & flags) == flags) return i;
    }
    return std::numeric_limits<uint32_t>::max();
}

bool ensure_staging_buffer(VulkanState& vk, VkDeviceSize size) {
    if (vk.staging_buffer != VK_NULL_HANDLE && vk.staging_capacity >= size) return true;
    if (vk.staging_buffer != VK_NULL_HANDLE) {
        vkDestroyBuffer(vk.device, vk.staging_buffer, nullptr);
        vk.staging_buffer = VK_NULL_HANDLE;
    }
    if (vk.staging_memory != VK_NULL_HANDLE) {
        vkFreeMemory(vk.device, vk.staging_memory, nullptr);
        vk.staging_memory = VK_NULL_HANDLE;
    }
    VkBufferCreateInfo bci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bci.size = size;
    bci.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    if (vkCreateBuffer(vk.device, &bci, nullptr, &vk.staging_buffer) != VK_SUCCESS) return false;
    VkMemoryRequirements req{};
    vkGetBufferMemoryRequirements(vk.device, vk.staging_buffer, &req);
    uint32_t memory_type = find_memory_type(vk, req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (memory_type == std::numeric_limits<uint32_t>::max()) return false;
    VkMemoryAllocateInfo alloc{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    alloc.allocationSize = req.size;
    alloc.memoryTypeIndex = memory_type;
    if (vkAllocateMemory(vk.device, &alloc, nullptr, &vk.staging_memory) != VK_SUCCESS) return false;
    if (vkBindBufferMemory(vk.device, vk.staging_buffer, vk.staging_memory, 0) != VK_SUCCESS) return false;
    vk.staging_capacity = size;
    return true;
}

void image_barrier(VkCommandBuffer cmd, VkImage image, VkImageLayout old_layout, VkImageLayout new_layout) {
    VkImageMemoryBarrier barrier{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
    barrier.oldLayout = old_layout;
    barrier.newLayout = new_layout;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = image;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 1;
    barrier.srcAccessMask = 0;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    VkPipelineStageFlags src_stage = VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT;
    VkPipelineStageFlags dst_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
    if (new_layout == VK_IMAGE_LAYOUT_PRESENT_SRC_KHR) {
        barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        barrier.dstAccessMask = 0;
        src_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
        dst_stage = VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT;
    }
    vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, nullptr, 0, nullptr, 1, &barrier);
}

bool render_scene_pixels(VulkanState& vk, const ParsedScene& scene, int logical_width, int logical_height) {
    if (!ensure_vulkan(vk)) return false;
    int width = static_cast<int>(vk.extent.width);
    int height = static_cast<int>(vk.extent.height);
    auto pixels = rasterize_scene_pixels(scene, width, height, logical_width, logical_height);
    VkDeviceSize byte_count = static_cast<VkDeviceSize>(pixels.size() * sizeof(uint32_t));
    if (!ensure_staging_buffer(vk, byte_count)) return false;
    void* mapped = nullptr;
    if (vkMapMemory(vk.device, vk.staging_memory, 0, byte_count, 0, &mapped) != VK_SUCCESS) return false;
    std::memcpy(mapped, pixels.data(), static_cast<size_t>(byte_count));
    vkUnmapMemory(vk.device, vk.staging_memory);

    uint32_t image_index = 0;
    VkResult acquire = vkAcquireNextImageKHR(vk.device, vk.swapchain, UINT64_MAX, vk.image_available, VK_NULL_HANDLE, &image_index);
    if (acquire == VK_ERROR_OUT_OF_DATE_KHR || acquire == VK_SUBOPTIMAL_KHR) {
        destroy_swapchain(vk);
        return create_swapchain(vk) && create_render_resources(vk) && render_scene_pixels(vk, scene, logical_width, logical_height);
    }
    if (acquire != VK_SUCCESS) return false;
    VkCommandBuffer cmd = vk.command_buffers[image_index];
    vkResetCommandBuffer(cmd, 0);
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    if (vkBeginCommandBuffer(cmd, &begin) != VK_SUCCESS) return false;
    image_barrier(cmd, vk.images[image_index], VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);
    VkBufferImageCopy region{};
    region.bufferOffset = 0;
    region.bufferRowLength = 0;
    region.bufferImageHeight = 0;
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.mipLevel = 0;
    region.imageSubresource.baseArrayLayer = 0;
    region.imageSubresource.layerCount = 1;
    region.imageOffset = {0, 0, 0};
    region.imageExtent = {vk.extent.width, vk.extent.height, 1};
    vkCmdCopyBufferToImage(cmd, vk.staging_buffer, vk.images[image_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
    image_barrier(cmd, vk.images[image_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR);
    if (vkEndCommandBuffer(cmd) != VK_SUCCESS) return false;
    VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    submit.waitSemaphoreCount = 1;
    submit.pWaitSemaphores = &vk.image_available;
    submit.pWaitDstStageMask = &wait_stage;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &cmd;
    submit.signalSemaphoreCount = 1;
    submit.pSignalSemaphores = &vk.render_finished;
    if (vkQueueSubmit(vk.queue, 1, &submit, VK_NULL_HANDLE) != VK_SUCCESS) return false;
    VkPresentInfoKHR present{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};
    present.waitSemaphoreCount = 1;
    present.pWaitSemaphores = &vk.render_finished;
    present.swapchainCount = 1;
    present.pSwapchains = &vk.swapchain;
    present.pImageIndices = &image_index;
    VkResult pr = vkQueuePresentKHR(vk.queue, &present);
    vkQueueWaitIdle(vk.queue);
    return pr == VK_SUCCESS || pr == VK_SUBOPTIMAL_KHR;
}

bool render_clear(VulkanState& vk, Rgba color) {
    if (!ensure_vulkan(vk)) return false;
    uint32_t image_index = 0;
    VkResult acquire = vkAcquireNextImageKHR(vk.device, vk.swapchain, UINT64_MAX, vk.image_available, VK_NULL_HANDLE, &image_index);
    if (acquire == VK_ERROR_OUT_OF_DATE_KHR || acquire == VK_SUBOPTIMAL_KHR) {
        destroy_swapchain(vk);
        return create_swapchain(vk) && create_render_resources(vk) && render_clear(vk, color);
    }
    if (acquire != VK_SUCCESS) return false;
    VkCommandBuffer cmd = vk.command_buffers[image_index];
    vkResetCommandBuffer(cmd, 0);
    VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    if (vkBeginCommandBuffer(cmd, &begin) != VK_SUCCESS) return false;
    VkClearValue clear{};
    clear.color.float32[0] = static_cast<float>(color.r) / 255.0f;
    clear.color.float32[1] = static_cast<float>(color.g) / 255.0f;
    clear.color.float32[2] = static_cast<float>(color.b) / 255.0f;
    clear.color.float32[3] = static_cast<float>(color.a) / 255.0f;
    VkRenderPassBeginInfo rp{VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO};
    rp.renderPass = vk.render_pass;
    rp.framebuffer = vk.framebuffers[image_index];
    rp.renderArea.offset = {0, 0};
    rp.renderArea.extent = vk.extent;
    rp.clearValueCount = 1;
    rp.pClearValues = &clear;
    vkCmdBeginRenderPass(cmd, &rp, VK_SUBPASS_CONTENTS_INLINE);
    vkCmdEndRenderPass(cmd);
    if (vkEndCommandBuffer(cmd) != VK_SUCCESS) return false;
    VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    VkSubmitInfo submit{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    submit.waitSemaphoreCount = 1;
    submit.pWaitSemaphores = &vk.image_available;
    submit.pWaitDstStageMask = &wait_stage;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &cmd;
    submit.signalSemaphoreCount = 1;
    submit.pSignalSemaphores = &vk.render_finished;
    if (vkQueueSubmit(vk.queue, 1, &submit, VK_NULL_HANDLE) != VK_SUCCESS) return false;
    VkPresentInfoKHR present{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};
    present.waitSemaphoreCount = 1;
    present.pWaitSemaphores = &vk.render_finished;
    present.swapchainCount = 1;
    present.pSwapchains = &vk.swapchain;
    present.pImageIndices = &image_index;
    VkResult pr = vkQueuePresentKHR(vk.queue, &present);
    vkQueueWaitIdle(vk.queue);
    return pr == VK_SUCCESS || pr == VK_SUBOPTIMAL_KHR;
}

}  // namespace

extern "C" JNIEXPORT jint JNICALL
Java_com_luvatrix_app_NativeVulkan_probeVulkan(JNIEnv *, jobject) {
    uint32_t extension_count = 0;
    VkResult result = vkEnumerateInstanceExtensionProperties(nullptr, &extension_count, nullptr);
    if (result != VK_SUCCESS) {
        LVX_LOGE("vkEnumerateInstanceExtensionProperties failed: %d", result);
        return 0;
    }
    LVX_LOGI("luvatrix vulkan probe ok extensions=%u", extension_count);
    return static_cast<jint>(extension_count);
}

extern "C" JNIEXPORT void JNICALL
Java_com_luvatrix_app_NativeVulkan_setSurface(JNIEnv *env, jobject, jobject surface) {
    std::lock_guard<std::mutex> lock(g_mutex);
    destroy_vulkan(g_vk);
    if (surface == nullptr) {
        LVX_LOGI("native Vulkan surface cleared");
        return;
    }
    g_vk.window = ANativeWindow_fromSurface(env, surface);
    if (g_vk.window == nullptr) {
        LVX_LOGE("ANativeWindow_fromSurface returned null");
        return;
    }
    LVX_LOGI(
        "native Vulkan surface set window=%p size=%dx%d",
        g_vk.window,
        ANativeWindow_getWidth(g_vk.window),
        ANativeWindow_getHeight(g_vk.window)
    );
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_setBitmapGlyphTable(JNIEnv *env, jobject, jstring tableText) {
    if (tableText == nullptr) return JNI_FALSE;
    const char* raw = env->GetStringUTFChars(tableText, nullptr);
    if (raw == nullptr) return JNI_FALSE;
    std::string table(raw);
    env->ReleaseStringUTFChars(tableText, raw);

    BitmapFont parsed;
    bool ok = parse_bitmap_font_table(table, parsed);
    if (!ok) {
        LVX_LOGE("luvatrix bitmap glyph table parse failed");
        return JNI_FALSE;
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    g_bitmap_font = std::move(parsed);
    LVX_LOGI(
        "luvatrix bitmap glyph table loaded glyphs=%zu size=%dx%d advance=%d",
        g_bitmap_font.glyphs.size(),
        g_bitmap_font.width,
        g_bitmap_font.height,
        g_bitmap_font.advance
    );
    return JNI_TRUE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_com_luvatrix_app_NativeVulkan_presentScene(
    JNIEnv *env,
    jobject,
    jstring sceneJson,
    jint revision,
    jint width,
    jint height
) {
    const char* raw = env->GetStringUTFChars(sceneJson, nullptr);
    if (raw == nullptr) return JNI_FALSE;
    std::string payload(raw);
    env->ReleaseStringUTFChars(sceneJson, raw);

    std::lock_guard<std::mutex> lock(g_mutex);
    g_vk.desired_width = std::max(1, static_cast<int>(width));
    g_vk.desired_height = std::max(1, static_cast<int>(height));
    ParsedScene scene = parse_scene(payload);
    bool ok = render_scene_pixels(g_vk, scene, width, height);
    if (ok && revision % 120 == 0) {
        LVX_LOGI(
            "luvatrix vulkan scene revision=%d size=%dx%d nodes=%d rects=%zu circles=%zu text=%zu rgba=%d,%d,%d,%d",
            revision,
            width,
            height,
            count_nodes(payload),
            scene.rects.size(),
            scene.circles.size(),
            scene.texts.size(),
            scene.background.r,
            scene.background.g,
            scene.background.b,
            scene.background.a
        );
    }
    return ok ? JNI_TRUE : JNI_FALSE;
}
